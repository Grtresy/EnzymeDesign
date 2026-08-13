from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import threading
import time
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest
import openzyme_core.agent_runtime as agent_runtime_module
from fastapi.testclient import TestClient
from openzyme_domain import SourceRefKind
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_host_api import HostApiDependencies
from openzyme_host_api import HostSecurityPolicy
from openzyme_host_api import build_local_eval_foundation
from openzyme_host_api import create_app
from openzyme_host_api.app import DrainV3RuntimeRequest
from openzyme_host_api.app import PostV3MessageRequest
from openzyme_host_api.app import _build_durable_work_supervisor
from openzyme_host_api.app import _iter_v3_event_stream
from openzyme_host_api.background_runtime import RuntimeSignalNotifier
from openzyme_host_api.background_runtime import V3BackgroundRuntimeService
from openzyme_host_api.background_runtime import V3DurableWorkCoordinator
from openzyme_host_api.background_runtime import V3DurableWorkSupervisor
from openzyme_runtime import ConstraintItem
from openzyme_runtime import ConstraintSet
from openzyme_runtime import DesignBriefDraft
from openzyme_runtime import DesignNextAction
from openzyme_runtime import ExecutionPlanDraft
from openzyme_runtime import IntakeClarification
from openzyme_runtime import IntakePhaseOutput
from openzyme_runtime import LangChainToolCallingInvoker
from openzyme_runtime import ReportDraft
from openzyme_runtime import ReliabilityRefactorSettings
from openzyme_runtime import ResearchBriefDraft as RuntimeResearchBriefDraft
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import get_llm_debug_recorder
from openzyme_tools import DefaultHpcExecutionRegistry
from openzyme_tools import RepoBackedHpcCatalogProvider
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult
from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationDispatchRequest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ContinuationDeliveryState
from openzyme_domain import ContinuationState
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import InboxParticipantKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import RetryEligibility
from openzyme_domain import RuntimeCommandRecord
from openzyme_domain import RuntimeCommandStatus
from openzyme_domain import RuntimeCommandType
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_core import EngineDescriptor
from openzyme_core import EngineDocumentRecord
from openzyme_core import EngineRegistry
from openzyme_core import AgentRuntimeService
from openzyme_core import HarnessResult
from openzyme_core import HarnessStatus
from openzyme_core import MutationScopeService
from openzyme_core import ProtocolService
from openzyme_core import CoreRepositories
from openzyme_core import DurableControlledOperationAdmission
from openzyme_core import DurableControlledOperationAdmissionService
from openzyme_core import DurableEventRepository
from openzyme_core import RuntimeWriteFencingError
from openzyme_core import runtime_command_request_digest
from openzyme_core import SandboxProcessHostAuthority
from openzyme_core import SessionTurnHostAuthority
from openzyme_core import SandboxWorkspaceService
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import apply_sqlite_migrations as apply_v3_sqlite_migrations
from openzyme_core import connect_sqlite as connect_v3_sqlite
from openzyme_core import sandbox_image_record
from openzyme_core import controlled_operation_approval_digest
from openzyme_core.workflow_knowledge import default_workflow_registry
from openzyme_engines import EvidenceSynthesis
from openzyme_engines import EvidenceSynthesisItem
from openzyme_engines import ExecutionParsedResult
from openzyme_engines import ResearchBriefDraft as EngineResearchBriefDraft
from openzyme_engines import ResearchSourceItem
from openzyme_engines import ResearchSupervisorAction
from openzyme_engines import ResearchUnitDraft as EngineResearchUnitDraft
from openzyme_engines import ResearchUnitPlan as EngineResearchUnitPlan
from openzyme_engines.execution import ExecutionStartResult
from openzyme_host_api.aox_scientific_contract import (
    AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
)
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import FAULT_ARTIFACT_BYTE_FLIP_ID
from openzyme_host_api.aox_fault_injection import (
    FAULT_INJECTION_CLAIM_DOCUMENT_KIND,
    FAULT_INJECTION_CLAIM_SCHEMA_ID,
    FAULT_INJECTION_RECEIPT_SCHEMA_ID,
    aox_fault_injection_request_digest,
)
from openzyme_host_api.aox_public_product_closure import (
    FAULT_INJECTION_RECEIPT_DOCUMENT_KIND,
)
from openzyme_host_api.host_mutation_observation import (
    HOST_MUTATION_ORIGINAL_STATUS_CODES,
    observe_host_mutation_operation,
)
from openzyme_host_api.v3_service import V3EventStore
from openzyme_host_api.v3_service import V3HostApiService


def test_v3_event_store_preserves_public_payload_and_filters_private_visibility() -> (
    None
):
    repositories = _build_v3_engine_repositories()
    event_store = V3EventStore(repositories)
    service = V3HostApiService(
        repositories=repositories,
        event_store=event_store,
    )
    service.create_session(
        project_id="proj_public_diagnostic",
        session_id="sess_public_diagnostic",
        title="Public diagnostic",
        objective="Verify durable public event sanitization.",
    )
    after_cursor = event_store.latest_cursor("sess_public_diagnostic")
    public_payload = {
        "message": "user-authored value /home/operator/literal",
        "scientific_locator": "https://example.org/search?query=AOX",
    }
    events = [
        {
            "event_id": "evt_public_diagnostic",
            "session_id": "sess_public_diagnostic",
            "event_type": "harness.failed",
            "created_at": "2026-07-18T00:00:00+00:00",
            "visibility": "public",
            "payload": public_payload,
        },
        {
            "event_id": "evt_audit_diagnostic",
            "session_id": "sess_public_diagnostic",
            "event_type": "harness.audit_diagnostic",
            "created_at": "2026-07-18T00:00:01+00:00",
            "visibility": "audit",
            "payload": {"error": "private audit diagnostic"},
        },
        {
            "event_id": "evt_internal_diagnostic",
            "session_id": "sess_public_diagnostic",
            "event_type": "harness.internal_diagnostic",
            "created_at": "2026-07-18T00:00:02+00:00",
            "visibility": "internal",
            "payload": {"error": "private Host diagnostic"},
        },
    ]

    stored = event_store.append("sess_public_diagnostic", events)
    replayed = event_store.list(
        "sess_public_diagnostic",
        after_cursor=after_cursor,
    )
    assert stored[0]["payload"] == public_payload
    assert stored[1]["visibility"] == "audit"
    assert stored[2]["visibility"] == "internal"
    assert [event["event_id"] for event in replayed] == ["evt_public_diagnostic"]
    assert {event["visibility"] for event in replayed} == {"public"}
    assert replayed[0]["payload"] == public_payload


def _local_test_security(*, debug_enabled: bool = True) -> HostSecurityPolicy:
    return HostSecurityPolicy(
        deployment_profile="local-dev",
        principals_by_digest={},
        debug_enabled=debug_enabled,
    )


class _ObservedRuntimeCommand:
    """Test-only view that keeps command admission and public reads explicit."""

    def __init__(self, *, admission_status_code: int, payload: dict[str, object]):
        self.status_code = admission_status_code
        self._payload = payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload, sort_keys=True)

    def json(self) -> dict[str, object]:
        return self._payload


_RUNTIME_COMMAND_SEQUENCE = itertools.count(1)


def _start_runtime_command_client(
    client: TestClient,
    request: pytest.FixtureRequest,
) -> None:
    client.__enter__()
    cleanup = getattr(client, "_openzyme_test_cleanup", None)

    def finalize() -> None:
        client.__exit__(None, None, None)
        if callable(cleanup):
            cleanup()

    request.addfinalizer(finalize)


def _provider_backed_test_repositories(
    client: TestClient,
    provider: SQLiteRepositoryProvider,
    owner: tempfile.TemporaryDirectory[str],
) -> CoreRepositories:
    observer_scope = provider.connection_scope()
    repositories = observer_scope.__enter__().repositories

    def cleanup() -> None:
        observer_scope.__exit__(None, None, None)
        owner.cleanup()

    setattr(client, "_openzyme_test_cleanup", cleanup)
    return repositories


def _read_public_events(
    client: TestClient,
    *,
    session_id: str,
    after_cursor: int,
) -> list[dict[str, object]]:
    response = client.get(
        f"/v3/sessions/{session_id}/events"
        f"?replay=1&after_cursor={after_cursor}"
    )
    assert response.status_code == 200, response.text
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _admit_and_observe_runtime_command(
    client: TestClient,
    *,
    session_id: str,
    request: dict[str, object] | None = None,
    timeout_seconds: float = 15.0,
) -> _ObservedRuntimeCommand:
    before_workspace_response = client.get(
        f"/v3/sessions/{session_id}/workspace"
    )
    assert before_workspace_response.status_code == 200, before_workspace_response.text
    before_workspace = before_workspace_response.json()
    before_conversation_count = len(before_workspace["conversation"])
    prior_events = _read_public_events(
        client,
        session_id=session_id,
        after_cursor=0,
    )
    after_cursor = max(
        (int(event.get("cursor") or 0) for event in prior_events),
        default=0,
    )
    admission = client.post(
        f"/v3/sessions/{session_id}/runtime/drain",
        headers={
            "Idempotency-Key": (
                f"test-runtime-drain:{session_id}:"
                f"{next(_RUNTIME_COMMAND_SEQUENCE)}"
            )
        },
        json=request or {},
    )
    assert admission.status_code == 202, admission.text
    admitted = admission.json()
    command_id = str(admitted["command_id"])
    status_url = str(admitted["status_url"])
    assert status_url == (
        f"/v3/sessions/{session_id}/runtime/commands/{command_id}"
    )
    deadline = time.monotonic() + timeout_seconds
    while True:
        observed_response = client.get(status_url)
        assert observed_response.status_code == 200, observed_response.text
        observed = observed_response.json()
        if observed["status"] in {
            "completed",
            "failed",
            "locked",
            "cancelled",
        }:
            break
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"runtime command {command_id!r} remained {observed['status']!r}"
            )
        time.sleep(0.01)

    workspace_response = client.get(f"/v3/sessions/{session_id}/workspace")
    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    events = _read_public_events(
        client,
        session_id=session_id,
        after_cursor=after_cursor,
    )
    new_conversation = workspace["conversation"][before_conversation_count:]
    outputs = [
        str(message["content"])
        for message in new_conversation
        if message.get("role") == "assistant"
    ]
    bounded_outcome = dict(observed.get("bounded_outcome_summary") or {})
    projection = {
        **observed,
        "command": observed,
        "status": bounded_outcome.get("scheduler_status", observed["status"]),
        "outputs": outputs,
        "events": events,
        "workspace": workspace,
        "processed_signal_count": bounded_outcome.get(
            "processed_signal_count",
            0,
        ),
        "suspended": bounded_outcome.get("suspended", False),
    }
    return _ObservedRuntimeCommand(
        admission_status_code=admission.status_code,
        payload=projection,
    )


def test_v3_durable_events_survive_host_restart_and_replay_from_cursor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bootstrap_client, foundation = _build_client(monkeypatch)
    del bootstrap_client
    provider = SQLiteRepositoryProvider(str(tmp_path / "durable-events.sqlite3"))
    first_dependencies = HostApiDependencies(
        foundation=foundation,
        v3_repository_provider=provider,
    )
    with TestClient(create_app(first_dependencies)) as first_client:
        created = first_client.post(
            "/v3/sessions",
            headers={"Idempotency-Key": "create-restart-session"},
            json={
                "session_id": "sess_restart_events",
                "project_id": "proj_restart_events",
                "objective": "Prove event replay after restart",
            },
        )
        assert created.status_code == 200
        first_event = created.json()["events"][0]
        assert first_event["cursor"] > 0

    second_dependencies = HostApiDependencies(
        foundation=foundation,
        v3_repository_provider=provider,
    )
    with TestClient(create_app(second_dependencies)) as second_client:
        replay = second_client.get(
            "/v3/sessions/sess_restart_events/events?replay=1"
        )
        assert replay.status_code == 200
        assert f"id: {first_event['cursor']}" in replay.text
        assert first_event["event_id"] in replay.text

        after = second_client.get(
            "/v3/sessions/sess_restart_events/events?replay=1",
            headers={"Last-Event-ID": str(first_event["cursor"])},
        )
        assert after.status_code == 200
        assert first_event["event_id"] not in after.text


def test_v3_event_replay_pages_past_one_thousand_and_filters_private_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bootstrap_client, foundation = _build_client(monkeypatch)
    del bootstrap_client
    provider = SQLiteRepositoryProvider(str(tmp_path / "event-pages.sqlite3"))
    dependencies = HostApiDependencies(
        foundation=foundation,
        security_policy=_local_test_security(),
        v3_repository_provider=provider,
    )
    session_id = "sess_event_pages"

    with TestClient(create_app(dependencies)) as client:
        created = client.post(
            "/v3/sessions",
            json={
                "session_id": session_id,
                "project_id": "proj_event_pages",
                "objective": "Replay every public event page.",
            },
        )
        assert created.status_code == 200
        after_cursor = int(created.json()["events"][-1]["cursor"])

        public_ids = [f"evt_page_{index:04d}" for index in range(1_005)]
        seeded_events: list[dict[str, object]] = []
        for index, event_id in enumerate(public_ids):
            if index == 500:
                seeded_events.append(
                    {
                        "event_id": "evt_page_audit",
                        "session_id": session_id,
                        "event_type": "page.audit",
                        "created_at": "2026-07-18T00:00:00+00:00",
                        "visibility": "audit",
                        "payload": {"private": "audit"},
                    }
                )
            seeded_events.append(
                {
                    "event_id": event_id,
                    "session_id": session_id,
                    "event_type": "page.public",
                    "created_at": "2026-07-18T00:00:00+00:00",
                    "visibility": "public",
                    "payload": {"index": index},
                }
            )
        seeded_events.append(
            {
                "event_id": "evt_page_internal",
                "session_id": session_id,
                "event_type": "page.internal",
                "created_at": "2026-07-18T00:00:00+00:00",
                "visibility": "internal",
                "payload": {"private": "internal"},
            }
        )
        with provider.write() as owner:
            V3EventStore(owner.repositories).append(session_id, seeded_events)

        replay = client.get(
            f"/v3/sessions/{session_id}/events"
            f"?replay=1&follow=0&after_cursor={after_cursor}"
        )
        no_replay = client.get(
            f"/v3/sessions/{session_id}/events"
            f"?replay=0&follow=0&after_cursor={after_cursor}"
        )

    assert replay.status_code == 200
    replayed = [
        json.loads(line.removeprefix("data: "))
        for line in replay.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [event["event_id"] for event in replayed] == public_ids
    assert {event["visibility"] for event in replayed} == {"public"}
    assert "evt_page_audit" not in replay.text
    assert "evt_page_internal" not in replay.text
    assert no_replay.status_code == 200
    assert no_replay.text == ""


def test_v3_event_stream_uses_request_high_watermark_for_replay_and_follow() -> (
    None
):
    events = [
        {
            "event_id": f"evt_{cursor}",
            "session_id": "sess_follow_watermark",
            "event_type": "follow.event",
            "schema_version": "openzyme.v3.event.v1",
            "visibility": "public",
            "created_at": "2026-07-18T00:00:00+00:00",
            "payload": {},
            "cursor": cursor,
        }
        for cursor in range(1, 1_003)
    ]
    replay_cursors: list[int] = []

    def read_replay_events(cursor: int) -> list[dict[str, object]]:
        replay_cursors.append(cursor)
        return [event for event in events if int(event["cursor"]) > cursor][:1_000]

    async def read_replay_snapshot() -> list[str]:
        return [
            encoded
            async for encoded in _iter_v3_event_stream(
                read_replay_events,
                requested_cursor=0,
                request_high_watermark=1_001,
                replay=True,
                follow=False,
                envelope=False,
            )
        ]

    snapshot = asyncio.run(read_replay_snapshot())

    assert len(snapshot) == 1_001
    assert replay_cursors == [0, 1_000]
    assert "id: 1001" in snapshot[-1]
    assert not any("id: 1002" in encoded for encoded in snapshot)

    observed_cursors: list[int] = []

    def read_events(cursor: int) -> list[dict[str, object]]:
        observed_cursors.append(cursor)
        return [event for event in events if int(event["cursor"]) > cursor][:1_000]

    async def read_first_follow_event() -> str:
        stream = _iter_v3_event_stream(
            read_events,
            requested_cursor=0,
            request_high_watermark=1_001,
            replay=False,
            follow=True,
            envelope=False,
            poll_interval_seconds=0,
        )
        try:
            return await anext(stream)
        finally:
            await stream.aclose()

    encoded = asyncio.run(read_first_follow_event())

    assert observed_cursors == [1_001]
    assert "id: 1002" in encoded
    assert '"event_id":"evt_1002"' in encoded


def test_v3_task_create_idempotency_replays_response_and_rejects_collision(
    monkeypatch,
) -> None:
    client, _ = _build_client(monkeypatch)
    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_idempotency",
            "project_id": "proj_idempotency",
            "objective": "Prove command receipts",
        },
    )
    assert created.status_code == 200
    request = {
        "session_id": "sess_idempotency",
        "task_id": "task_idempotency",
        "subject": "Create exactly once",
        "description": "Retry-safe task creation",
    }
    headers = {"Idempotency-Key": "create-task-once"}

    first = client.post("/v3/tasks", headers=headers, json=request)
    second = client.post("/v3/tasks", headers=headers, json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    events = client.get("/v3/sessions/sess_idempotency/events?replay=1")
    assert events.text.count("event: task.created") == 1

    conflict = client.post(
        "/v3/tasks",
        headers=headers,
        json={**request, "subject": "Conflicting retry"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert "different request" in conflict.json()["error"]["message"]


def test_v3_host_mutation_observation_reads_existing_production_owners(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bootstrap, foundation = _build_client(monkeypatch)
    del bootstrap
    provider = SQLiteRepositoryProvider(str(tmp_path / "mutation-observe.sqlite3"))
    dependencies = HostApiDependencies(
        foundation=foundation,
        security_policy=_local_test_security(),
        v3_repository_provider=provider,
        v3_background_runtime_enabled=False,
    )
    session_id = "sess_mutation_observe"
    project_id = "proj_mutation_observe"

    def observe(client: TestClient, **params: str):
        return client.get("/v3/mutation-operations/observe", params=params)

    with TestClient(create_app(dependencies)) as client:
        created = client.post(
            "/v3/sessions",
            headers={"Idempotency-Key": "observe-session-create"},
            json={
                "session_id": session_id,
                "project_id": project_id,
                "objective": "Read existing durable mutation owners.",
            },
        )
        assert created.status_code == 200
        task = client.post(
            "/v3/tasks",
            headers={"Idempotency-Key": "observe-task-create"},
            json={
                "session_id": session_id,
                "task_id": "task_mutation_observe",
                "subject": "Observe exact task receipt",
            },
        )
        assert task.status_code == 200
        with provider.read() as reader:
            task_owner = reader.repositories.command_receipts.find(
                scope_ref=f"session:{session_id}",
                command_type="task.create",
                idempotency_key="observe-task-create",
            )
            assert task_owner is not None
            before_counts = tuple(
                int(
                    reader.connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                )
                for table in (
                    "command_receipt_records",
                    "runtime_command_records",
                    "scientific_attempt_authorization_records",
                    "engine_documents",
                )
            )
        task_observation = observe(
            client,
            session_id=session_id,
            command_type="task.create",
            scope_ref=f"session:{session_id}",
            idempotency_key="observe-task-create",
            request_digest=task_owner.request_digest,
        )
        assert task_observation.status_code == 200
        assert task_observation.json()["status"] == "terminal"
        assert task_observation.json()["response"] == task.json()

        absent = observe(
            client,
            session_id=session_id,
            command_type="task.create",
            scope_ref=f"session:{session_id}",
            idempotency_key="observe-absent",
            request_digest="sha256:" + "a" * 64,
        )
        assert absent.status_code == 200
        assert absent.json()["status"] == "unproven"
        assert absent.json()["effect_certainty"] == "unproven"
        assert absent.json()["reconciliation_required"] is True
        with provider.read() as reader:
            after_counts = tuple(
                int(
                    reader.connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                )
                for table in (
                    "command_receipt_records",
                    "runtime_command_records",
                    "scientific_attempt_authorization_records",
                    "engine_documents",
                )
            )
        assert after_counts == before_counts

        runtime_digest = runtime_command_request_digest(
            session_id=session_id,
            command_type=RuntimeCommandType.RUNTIME_DRAIN,
            max_signals=3,
            max_steps_per_agent=8,
            auto_enqueue_ready_tasks=False,
        )
        with provider.connection_scope() as owner:
            owner.repositories.runtime_commands.add(
                RuntimeCommandRecord(
                    command_id="runtime_observe_in_progress",
                    session_id=session_id,
                    command_type=RuntimeCommandType.RUNTIME_DRAIN,
                    request_digest=runtime_digest,
                    idempotency_key="runtime-observe-in-progress",
                    status=RuntimeCommandStatus.ACCEPTED,
                    max_signals=3,
                    max_steps_per_agent=8,
                    auto_enqueue_ready_tasks=False,
                    state_version=1,
                    fencing_token=0,
                    accepted_at="2026-08-13T00:00:00+00:00",
                )
            )
            owner.repositories.runtime_commands.add(
                RuntimeCommandRecord(
                    command_id="runtime_observe_terminal",
                    session_id=session_id,
                    command_type=RuntimeCommandType.RUNTIME_DRAIN,
                    request_digest=runtime_digest,
                    idempotency_key="runtime-observe-terminal",
                    status=RuntimeCommandStatus.COMPLETED,
                    max_signals=3,
                    max_steps_per_agent=8,
                    auto_enqueue_ready_tasks=False,
                    state_version=2,
                    fencing_token=1,
                    accepted_at="2026-08-13T00:00:00+00:00",
                    started_at="2026-08-13T00:00:01+00:00",
                    completed_at="2026-08-13T00:00:02+00:00",
                )
            )
        in_progress = observe(
            client,
            session_id=session_id,
            command_type="runtime.drain",
            scope_ref=f"session:{session_id}",
            idempotency_key="runtime-observe-in-progress",
            request_digest=runtime_digest,
        )
        assert in_progress.status_code == 200
        assert in_progress.json()["status"] == "in_progress"
        assert in_progress.json()["effect_certainty"] == "unproven"
        terminal_runtime = observe(
            client,
            session_id=session_id,
            command_type="runtime.drain",
            scope_ref=f"session:{session_id}",
            idempotency_key="runtime-observe-terminal",
            request_digest=runtime_digest,
        )
        assert terminal_runtime.status_code == 200
        assert terminal_runtime.json()["status"] == "terminal"

        lane = client.post(
            "/v3/lanes",
            headers={"Idempotency-Key": "observe-lane"},
            json={
                "session_id": session_id,
                "lane_id": "lane_mutation_observe",
                "name": "formal",
            },
        )
        assert lane.status_code == 200
        authorization = client.post(
            f"/v3/sessions/{session_id}/scientific-attempt-authorizations",
            headers={"Idempotency-Key": "observe-scientific-authority"},
            json={
                "task_id": "task_mutation_observe",
                "campaign_id": "campaign_mutation_observe",
                "workflow_id": "aox_blank_world",
                "root_ref": "formal-slots/observe/1/root",
                "grantor_kind": "operator",
                "allowed_scopes": ["formal"],
                "allowed_effect_classes": ["provider", "hpc"],
                "max_attempts": 1,
                "max_micu": 10,
                "max_cost_microunits": 20,
                "max_wall_time_seconds": 30,
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        )
        assert authorization.status_code == 200, authorization.text
        authorization_digest = authorization.json()["record"]["request_digest"]
        scientific = observe(
            client,
            session_id=session_id,
            command_type="scientific.authorization.grant",
            scope_ref=f"session:{session_id}",
            idempotency_key="observe-scientific-authority",
            request_digest=authorization_digest,
        )
        assert scientific.status_code == 200
        assert scientific.json()["status"] == "terminal"
        with provider.read() as reader:
            service = V3HostApiService(
                repositories=reader.repositories,
                event_store=V3EventStore(reader.repositories),
            )
            principal_drift = observe_host_mutation_operation(
                service,
                principal_id="user:different",
                session_id=session_id,
                command_type="scientific.authorization.grant",
                scope_ref=f"session:{session_id}",
                idempotency_key="observe-scientific-authority",
                expected_request_digest=authorization_digest,
            )
        assert principal_drift["status"] == "unproven"

        attempt_id = "attempt_mutation_observe"
        artifact_id = "artifact_mutation_observe"
        fault_key = "observe-fault"
        fault_digest = aox_fault_injection_request_digest(
            session_id=session_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            idempotency_key=fault_key,
        )
        identity = canonical_digest(
            {
                "session_id": session_id,
                "attempt_id": attempt_id,
                "artifact_id": artifact_id,
                "injection_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
            }
        ).removeprefix("sha256:")[:32]
        claim_payload = {
            "schema_id": FAULT_INJECTION_CLAIM_SCHEMA_ID,
            "session_id": session_id,
            "attempt_id": attempt_id,
            "target_artifact_id": artifact_id,
            "actor_ref": "user:local-dev",
            "idempotency_key": fault_key,
            "request_digest": fault_digest,
        }
        with provider.connection_scope() as owner:
            owner.repositories.engine_documents.save(
                EngineDocumentRecord(
                    document_id=f"aox_fault_claim_{identity}",
                    session_id=session_id,
                    document_kind=FAULT_INJECTION_CLAIM_DOCUMENT_KIND,
                    payload=claim_payload,
                    created_at="2026-08-13T00:00:00+00:00",
                    updated_at="2026-08-13T00:00:00+00:00",
                )
            )
        claimed = observe(
            client,
            session_id=session_id,
            command_type="aox.reference-fault.inject",
            scope_ref=f"session:{session_id}",
            idempotency_key=fault_key,
            request_digest=fault_digest,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
        )
        assert claimed.status_code == 200
        assert claimed.json()["status"] == "in_progress"
        receipt_payload = {
            **claim_payload,
            "schema_id": FAULT_INJECTION_RECEIPT_SCHEMA_ID,
        }
        with provider.connection_scope() as owner:
            owner.repositories.engine_documents.save(
                EngineDocumentRecord(
                    document_id=f"aox_fault_receipt_{identity}",
                    session_id=session_id,
                    document_kind=FAULT_INJECTION_RECEIPT_DOCUMENT_KIND,
                    payload=receipt_payload,
                    created_at="2026-08-13T00:00:01+00:00",
                    updated_at="2026-08-13T00:00:01+00:00",
                )
            )
        completed_fault = observe(
            client,
            session_id=session_id,
            command_type="aox.reference-fault.inject",
            scope_ref=f"session:{session_id}",
            idempotency_key=fault_key,
            request_digest=fault_digest,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
        )
        assert completed_fault.status_code == 200
        assert completed_fault.json()["status"] == "terminal"

        request_drift = observe(
            client,
            session_id=session_id,
            command_type="task.create",
            scope_ref=f"session:{session_id}",
            idempotency_key="observe-task-create",
            request_digest="sha256:" + "f" * 64,
        )
        assert request_drift.status_code == 409
        session_drift = observe(
            client,
            session_id="sess_different",
            command_type="task.create",
            scope_ref=f"session:{session_id}",
            idempotency_key="observe-task-create",
            request_digest=task_owner.request_digest,
        )
        assert session_drift.status_code == 400


def test_host_mutation_original_status_codes_match_registered_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap, foundation = _build_client(monkeypatch)
    del bootstrap
    app = create_app(
        HostApiDependencies(
            foundation=foundation,
            security_policy=_local_test_security(),
        )
    )
    command_routes = {
        "session.create": ("/v3/sessions", "POST"),
        "conversation.message.post": (
            "/v3/sessions/{session_id}/messages",
            "POST",
        ),
        "task.create": ("/v3/tasks", "POST"),
        "task.update": ("/v3/tasks/{task_id}", "PATCH"),
        "lane.create": ("/v3/lanes", "POST"),
        "lane.claim": ("/v3/lanes/{lane_id}/claim", "POST"),
        "lane.keep": ("/v3/lanes/{lane_id}/keep", "POST"),
        "lane.remove": ("/v3/lanes/{lane_id}/remove", "POST"),
        "approval.resolve": ("/v3/approvals/{approval_id}/resolve", "POST"),
        "runtime.drain": ("/v3/sessions/{session_id}/runtime/drain", "POST"),
        "scientific.authorization.grant": (
            "/v3/sessions/{session_id}/scientific-attempt-authorizations",
            "POST",
        ),
        "aox.reference-fault.inject": (
            "/v3/sessions/{session_id}/aox-fault-injections/reference-byte-flip",
            "POST",
        ),
    }
    registered = {
        command_type: next(
            (route.status_code or 200)
            for route in app.routes
            if getattr(route, "path", None) == path
            and method in (getattr(route, "methods", None) or set())
        )
        for command_type, (path, method) in command_routes.items()
    }
    assert registered == HOST_MUTATION_ORIGINAL_STATUS_CODES


def test_v3_public_contract_rejects_unknown_and_client_owned_actor_fields(
    monkeypatch,
) -> None:
    client, _ = _build_client(monkeypatch)
    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_strict_contract",
            "project_id": "proj_strict_contract",
            "objective": "Keep public commands explicit",
        },
    )
    assert created.status_code == 200

    unknown_task_field = client.post(
        "/v3/tasks",
        json={
            "session_id": "sess_strict_contract",
            "subject": "Reject typo",
            "unexpected": True,
        },
    )
    client_owned_lane_actor = client.post(
        "/v3/lanes/missing/claim",
        json={"claimed_ref": "client:forged"},
    )
    client_owned_approval_actor = client.post(
        "/v3/approvals/missing/resolve",
        json={"decision": "approved", "actor_ref": "client:forged"},
    )

    for response in (
        unknown_task_field,
        client_owned_lane_actor,
        client_owned_approval_actor,
    ):
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "request_validation_error"
        assert error["details"]


def test_v3_scientific_attempt_authority_and_read_only_surface(
    monkeypatch,
) -> None:
    client, _ = _build_client(monkeypatch)
    session_id = "sess_scientific_surface"
    assert (
        client.post(
            "/v3/sessions",
            json={
                "session_id": session_id,
                "project_id": "proj_scientific_surface",
                "objective": "Expose bounded scientific attempt authority",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v3/lanes",
            headers={"Idempotency-Key": "lane-scientific"},
            json={
                "session_id": session_id,
                "lane_id": "lane_scientific_surface",
                "name": "formal",
                "cwd": ".",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v3/tasks",
            headers={"Idempotency-Key": "task-scientific"},
            json={
                "session_id": session_id,
                "task_id": "task_scientific_surface",
                "subject": "Run selected-chain workflow",
                "lane_id": "lane_scientific_surface",
            },
        ).status_code
        == 200
    )
    authorization = client.post(
        f"/v3/sessions/{session_id}/scientific-attempt-authorizations",
        headers={"Idempotency-Key": "authorize-scientific"},
        json={
            "task_id": "task_scientific_surface",
            "campaign_id": "campaign_scientific_surface",
            "workflow_id": "aox_blank_world",
            "root_ref": "attempts/aox-scientific-surface",
            "allowed_scopes": ["formal"],
            "allowed_effect_classes": ["provider", "hpc"],
            "allowed_providers": ["openai"],
            "allowed_hpc_targets": ["hpc:approved"],
            "max_attempts": 2,
            "max_micu": 100,
            "max_cost_microunits": 10000,
            "max_wall_time_seconds": 7200,
            "expires_at": "2099-01-01T00:00:00+00:00",
        },
    )
    assert authorization.status_code == 200, authorization.text
    assert authorization.json()["record"]["status"] == "active"

    retired_command = client.post(
        f"/v3/sessions/{session_id}/scientific-attempt-commands",
        headers={"Idempotency-Key": "attempt-scientific"},
        json={
            "command": "attempt.create",
            "arguments": {},
        },
    )
    retired_admission_finalizer = client.post(
        f"/v3/sessions/{session_id}/scientific-attempt-admissions/finalize",
        headers={"Idempotency-Key": "finalize-attempt-scientific"},
        json={"admission_request_id": "legacy"},
    )
    retired_closure_finalizer = client.post(
        f"/v3/sessions/{session_id}/scientific-attempt-closures/finalize",
        headers={"Idempotency-Key": "finalize-closure-scientific"},
        json={"closure_request_id": "legacy"},
    )
    assert retired_command.status_code == 404
    assert retired_admission_finalizer.status_code == 404
    assert retired_closure_finalizer.status_code == 404

    inspected = client.get(f"/v3/sessions/{session_id}/scientific-attempts")
    workspace = client.get(f"/v3/sessions/{session_id}/workspace")
    assert inspected.status_code == 200
    assert inspected.json()["authorizations"][0]["attempts"]["remaining"] == 2
    assert inspected.json()["admission_request_count"] == 0
    assert inspected.json()["attempts"] == []
    assert "allowed_providers" not in json.dumps(inspected.json())
    assert (
        workspace.json()["scientific_attempts"]["schema_id"]
        == "scientific_attempt_readiness_summary@1"
    )
    assert "occurrences" not in json.dumps(
        workspace.json()["scientific_attempts"]
    )

    incomplete_filter = client.get(
        f"/v3/sessions/{session_id}/scientific-attempts",
        params={"attempt_id": "not-publicly-created"},
    )
    assert incomplete_filter.status_code == 409
    assert incomplete_filter.json()["error"]["code"] == (
        "scientific_inspection_filter_incomplete"
    )

def test_v3_closed_attempt_evidence_export_is_public_and_exact(
    monkeypatch,
) -> None:
    client, _ = _build_client(monkeypatch)
    session_id = "sess_closed_evidence"
    created = client.post(
        "/v3/sessions",
        json={
            "session_id": session_id,
            "project_id": "proj_closed_evidence",
            "objective": "Export one exact closed attempt",
        },
    )
    assert created.status_code == 200
    captured: dict[str, str] = {}

    def export_exact(
        self,
        *,
        session_id: str,
        attempt_id: str,
        selection_id: str,
    ) -> dict[str, object]:
        del self
        captured.update(
            session_id=session_id,
            attempt_id=attempt_id,
            selection_id=selection_id,
        )
        return {
            "schema_id": "aox_closed_attempt_evidence@2",
            "session_id": session_id,
            "attempt_id": attempt_id,
            "selection_id": selection_id,
            "scientific_attempt_control": {},
            "finalization_receipt": None,
            "deliverables": [],
            "product_closure": {},
            "export_digest": "sha256:" + "a" * 64,
        }

    monkeypatch.setattr(
        V3HostApiService,
        "export_closed_aox_attempt_evidence",
        export_exact,
    )
    response = client.get(
        f"/v3/sessions/{session_id}/scientific-attempts/attempt_exact/"
        "selections/selection_exact/evidence"
    )

    assert response.status_code == 200
    assert captured == {
        "session_id": session_id,
        "attempt_id": "attempt_exact",
        "selection_id": "selection_exact",
    }
    assert response.json()["schema_id"] == "aox_closed_attempt_evidence@2"
    missing_session = client.get(
        "/v3/sessions/sess_other/scientific-attempts/attempt_exact/"
        "selections/selection_exact/evidence"
    )
    assert missing_session.status_code == 404


def test_v3_exact_aox_fault_capability_is_public_and_closed(
    monkeypatch,
) -> None:
    client, _ = _build_client(monkeypatch)
    session_id = "sess_exact_aox_fault"
    assert (
        client.post(
            "/v3/sessions",
            json={
                "session_id": session_id,
                "project_id": "proj_exact_aox_fault",
                "objective": "Exercise the exact fault capability",
            },
        ).status_code
        == 200
    )
    captured: dict[str, str] = {}

    def inject_exact(
        self,
        *,
        session_id: str,
        attempt_id: str,
        artifact_id: str,
        actor_ref: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        del self
        captured.update(
            session_id=session_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            actor_ref=actor_ref,
            idempotency_key=idempotency_key,
        )
        return {
            "schema_id": "aox_fault_injection_receipt@1",
            "injection_id": "derived_required_artifact_blob_byte_flip@2",
        }

    monkeypatch.setattr(V3HostApiService, "inject_aox_reference_fault", inject_exact)
    response = client.post(
        f"/v3/sessions/{session_id}/aox-fault-injections/reference-byte-flip",
        headers={"Idempotency-Key": "fault-once"},
        json={"attempt_id": "attempt_fault", "artifact_id": "artifact_ref21"},
    )

    assert response.status_code == 200
    assert captured == {
        "session_id": session_id,
        "attempt_id": "attempt_fault",
        "artifact_id": "artifact_ref21",
        "actor_ref": "user:local-dev",
        "idempotency_key": "fault-once",
    }
    malformed = client.post(
        f"/v3/sessions/{session_id}/aox-fault-injections/reference-byte-flip",
        headers={"Idempotency-Key": "fault-arbitrary"},
        json={
            "attempt_id": "attempt_fault",
            "artifact_id": "artifact_ref21",
            "byte_offset": 7,
        },
    )
    assert malformed.status_code == 422


def test_v3_event_stream_can_use_stable_generic_envelope(monkeypatch) -> None:
    client, _ = _build_client(monkeypatch)
    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_event_envelope",
            "project_id": "proj_event_envelope",
            "objective": "Preserve future event types",
        },
    )
    assert created.status_code == 200

    events = client.get(
        "/v3/sessions/sess_event_envelope/events?replay=1&envelope=1"
    )

    assert events.status_code == 200
    assert "event: openzyme.event" in events.text
    assert '"event_type":"session.created"' in events.text


def test_v3_runtime_health_is_public_and_sanitized(monkeypatch) -> None:
    client, _ = _build_client(monkeypatch)

    response = client.get("/v3/runtime/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "v3.runtime_health.v1"
    assert payload["deployment_profile"] == "local-dev"
    assert payload["storage_profile"] == "single_process_sqlite"
    assert payload["status"] in {"ready", "degraded"}
    assert {
        "control_plane",
        "model",
        "background_runtime",
        "execution",
        "web_research",
        "bio_research",
        "sandbox",
    } <= payload["components"].keys()
    serialized = json.dumps(payload)
    assert "worker_id" not in serialized
    assert "last_error" not in serialized
    assert "secret" not in serialized.lower()


def test_v3_workspace_api_projects_closed_sandbox_stdio_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bootstrap_client, foundation = _build_client(monkeypatch)
    del bootstrap_client
    provider = SQLiteRepositoryProvider(str(tmp_path / "stdio-metadata.sqlite3"))
    dependencies = HostApiDependencies(
        foundation=foundation,
        security_policy=_local_test_security(),
        v3_repository_provider=provider,
        v3_sandbox_workspace_root=tmp_path / "workspaces",
    )
    session_id = "sess_stdio_metadata"

    with TestClient(create_app(dependencies)) as client:
        created = client.post(
            "/v3/sessions",
            json={
                "session_id": session_id,
                "project_id": "proj_stdio_metadata",
                "objective": "Project closed sandbox stdio metadata.",
            },
        )
        assert created.status_code == 200
        with provider.write() as owner:
            repositories = owner.repositories
            agent = AgentMember(
                agent_id="agent:executor:stdio",
                session_id=session_id,
                lane_id=None,
                task_id=None,
                name="Executor",
                role="executor",
                status=AgentMemberStatus.IDLE,
                parent_agent_id="agent:master",
                created_at="2026-07-18T00:00:00+00:00",
                updated_at="2026-07-18T00:00:00+00:00",
                member_id="member_executor_stdio",
            )
            repositories.agents.save(agent)
            repositories.sandbox_images.save(
                sandbox_image_record(
                    image_ref="localhost/openzyme-pipeline-sandbox@sha256:stdio",
                    image_digest="sha256:stdio",
                )
            )
            workspace = SandboxWorkspaceService(
                repositories,
                workspace_root=tmp_path / "workspaces",
            ).create_or_get(
                session_id=session_id,
                agent_member_id="member_executor_stdio",
            )
            repositories.sandbox_runs.save(
                SandboxRunRecord(
                    sandbox_run_id="srun_stdio_metadata",
                    session_id=session_id,
                    sandbox_workspace_id=workspace.sandbox_workspace_id,
                    agent_id=agent.agent_id,
                    argv=("python", "src/probe.py"),
                    argv_digest="sha256:argv",
                    cwd="/workspace",
                    env_digest="sha256:env",
                    status=SandboxRunStatus.COMPLETED,
                    stdout_summary="bounded stdout",
                    stderr_summary="bounded stderr",
                    stdout_metadata={
                        "raw_digest": "sha256:stdout",
                        "raw_size_bytes": 40000,
                        "truncated": True,
                        "log_ref": "sandbox-log://srun_stdio_metadata/stdout",
                    },
                    stderr_metadata={
                        "raw_digest": "sha256:stderr",
                        "raw_size_bytes": 41000,
                        "truncated": True,
                        "log_ref": "sandbox-log://srun_stdio_metadata/stderr",
                    },
                    created_at="2026-07-18T00:00:01+00:00",
                    updated_at="2026-07-18T00:00:02+00:00",
                )
            )

        response = client.get(f"/v3/sessions/{session_id}/workspace")

    assert response.status_code == 200
    sandbox_run = response.json()["sandbox_runs"][0]
    assert sandbox_run["stdout_metadata"]["log_ref"].endswith("/stdout")
    assert sandbox_run["stderr_metadata"]["log_ref"].endswith("/stderr")
    assert sandbox_run["stdout_metadata"]["raw_size_bytes"] == 40000
    assert sandbox_run["stderr_metadata"]["raw_size_bytes"] == 41000
    assert "/home/" not in json.dumps(sandbox_run, sort_keys=True)


def test_v3_pending_approval_and_resolve_stay_bounded_with_large_artifact_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bootstrap_client, foundation = _build_client(monkeypatch)
    del bootstrap_client
    provider = SQLiteRepositoryProvider(str(tmp_path / "bounded-workspace.sqlite3"))
    dependencies = HostApiDependencies(
        foundation=foundation,
        security_policy=_local_test_security(),
        v3_repository_provider=provider,
        v3_sandbox_workspace_root=tmp_path / "workspaces",
    )
    session_id = "sess_bounded_workspace"
    approval_id = "appr_bounded_workspace"
    large_sequence_map = {
        f"P{index:05d}": f"sequence-payload-{index:05d}-" + "x" * 80
        for index in range(10_000)
    }

    with TestClient(create_app(dependencies)) as client:
        created = client.post(
            "/v3/sessions",
            json={
                "session_id": session_id,
                "project_id": "proj_bounded_workspace",
                "objective": "Keep composite reads independent of exact metadata size.",
            },
        )
        assert created.status_code == 200
        with provider.write() as owner:
            owner.repositories.artifacts.save(
                SessionArtifactRecord(
                    artifact_id="art_large_metadata",
                    session_id=session_id,
                    task_id=None,
                    lane_id=None,
                    invocation_id=None,
                    run_id=None,
                    kind=ArtifactKind.RESULT,
                    storage_uri="/private/artifacts/large-metadata.json",
                    relative_path="formal/large-metadata.json",
                    title="Large canonical metadata",
                    description=None,
                    metadata={
                        "schema_id": "large_scientific_metadata@1",
                        "content_digest": f"sha256:{'a' * 64}",
                        "sequence_count": len(large_sequence_map),
                        "sequence_digests": large_sequence_map,
                    },
                    created_at="2026-07-20T12:00:00+00:00",
                )
            )
            owner.repositories.approvals.save(
                ApprovalRequest(
                    approval_id=approval_id,
                    session_id=session_id,
                    task_id=None,
                    lane_id=None,
                    kind="execution_launch",
                    requested_action="Approve bounded projection test",
                    status=ApprovalRequestStatus.PENDING,
                    request_ref="artifact://approvals/bounded.json",
                    resolution_ref=None,
                    created_at="2026-07-20T12:00:01+00:00",
                )
            )

        compact = client.get(f"/v3/sessions/{session_id}/pending-approvals")
        workspace = client.get(f"/v3/sessions/{session_id}/workspace")
        resolved = client.post(
            f"/v3/approvals/{approval_id}/resolve",
            json={"decision": "approved"},
        )

    assert compact.status_code == 200
    assert compact.json() == {
        "session_id": session_id,
        "pending_approvals": workspace.json()["pending_approvals"],
    }
    assert resolved.status_code == 200
    resolved_payload = resolved.json()
    resolved_json = json.dumps(
        resolved_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert len(resolved_json) < 250_000
    assert "sequence-payload-00000" not in resolved_json
    projected_artifact = next(
        item
        for item in resolved_payload["workspace"]["artifacts"]
        if item["artifact_id"] == "art_large_metadata"
    )
    assert projected_artifact["metadata"]["sequence_count"] == 10_000
    assert "sequence_digests" not in projected_artifact["metadata"]
    assert projected_artifact["metadata_summary"]["original_json_chars"] > 1_000_000
    assert projected_artifact["metadata_summary"]["omitted_field_count"] >= 1
    with provider.read() as owner:
        durable_artifact = owner.repositories.artifacts.get("art_large_metadata")
    assert durable_artifact is not None
    assert durable_artifact.metadata["sequence_digests"] == large_sequence_map


def test_v3_runtime_health_marks_local_fixtures_non_cutover() -> None:
    client = TestClient(
        create_app(
            HostApiDependencies(
                foundation=build_local_eval_foundation(),
                security_policy=_local_test_security(),
                v3_pipeline_sandbox_runner=FixtureNonCutoverPipelineSandboxRunner(),
            )
        )
    )

    payload = client.get("/v3/runtime/health").json()

    for component_name in ("model", "execution", "web_research", "bio_research"):
        assert payload["components"][component_name]["status"] == "fixture_non_cutover"
    assert payload["status"] == "degraded"


def test_v3_event_insert_failure_rolls_back_local_command(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider = SQLiteRepositoryProvider(str(tmp_path / "event-rollback.sqlite3"))
    def fail_event_append(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise RuntimeError("forced durable event failure")

    monkeypatch.setattr(DurableEventRepository, "append", fail_event_append)
    with pytest.raises(RuntimeError, match="forced durable event failure"):
        with provider.write() as owner:
            service = V3HostApiService(
                repositories=owner.repositories,
                event_store=V3EventStore(owner.repositories),
            )
            service.create_session(
                session_id="sess_rolled_back",
                project_id="proj_rolled_back",
                objective="This command must roll back",
            )

    with provider.read() as owner:
        assert owner.repositories.sessions.get("sess_rolled_back") is None
        assert owner.repositories.agents.list_by_session("sess_rolled_back") == []


def test_v3_execution_callback_scope_inherits_runtime_fence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bootstrap_client, foundation = _build_client(monkeypatch)
    del bootstrap_client
    provider = SQLiteRepositoryProvider(str(tmp_path / "callback-fence.sqlite3"))
    dependencies = HostApiDependencies(
        foundation=foundation,
        v3_repository_provider=provider,
    )
    session = Session.create(
        "sess_callback_fence",
        "proj_001",
        "Callback fence",
        "Reject stale sandbox callback writes",
    )
    with provider.write() as owner:
        owner.repositories.sessions.save(session)
    with provider.connection_scope() as coordinator:
        acquired = coordinator.repositories.session_runtime_leases.acquire(
            session_id=session.session_id,
            owner_id="worker:callback",
            mode="test",
            lease_seconds=60,
        )
        assert acquired.lease is not None
        registry = dependencies.build_v3_engine_registry(
            coordinator.repositories,
            acquired.lease,
        )
        execution_engine = registry.require("execution")
        callback_scope = execution_engine.sandbox_host_call_context_factory
        assert callback_scope is not None

        coordinator.connection.execute(
            "UPDATE session_runtime_leases SET expires_at = ? WHERE lease_token = ?",
            ("2020-01-01T00:00:00+00:00", acquired.lease.lease_token),
        )
        coordinator.connection.commit()
        replacement = coordinator.repositories.session_runtime_leases.acquire(
            session_id=session.session_id,
            owner_id="worker:replacement",
            mode="test",
            lease_seconds=60,
        )
        assert replacement.acquired is True

        with pytest.raises(RuntimeWriteFencingError, match="stale business write"):
            with callback_scope(
                session_id=session.session_id,
                invocation_id="inv_stale_callback",
            ):
                pass


def test_v3_sandbox_process_host_context_does_not_inherit_released_turn_lease(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bootstrap_client, foundation = _build_client(monkeypatch)
    del bootstrap_client
    provider = SQLiteRepositoryProvider(str(tmp_path / "host-context.sqlite3"))
    dependencies = HostApiDependencies(
        foundation=foundation,
        v3_repository_provider=provider,
    )
    session = Session.create(
        "sess_host_context",
        "proj_001",
        "Host context",
        "Keep the sandbox process independent from the launching turn",
    )
    with provider.write() as owner:
        owner.repositories.sessions.save(session)
    with provider.connection_scope() as coordinator:
        acquired = coordinator.repositories.session_runtime_leases.acquire(
            session_id=session.session_id,
            owner_id="worker:launching-turn",
            mode="test",
            lease_seconds=60,
        )
        assert acquired.lease is not None
        registry = dependencies.build_v3_engine_registry(
            coordinator.repositories,
            acquired.lease,
        )
        binding = dependencies.build_v3_sandbox_host_binding(
            registry,
            acquired.lease,
        )
        stale_session_authority = SessionTurnHostAuthority.from_lease(
            acquired.lease
        )

        coordinator.connection.execute(
            "UPDATE session_runtime_leases SET expires_at = ? WHERE lease_token = ?",
            ("2020-01-01T00:00:00+00:00", acquired.lease.lease_token),
        )
        coordinator.connection.commit()
        replacement = coordinator.repositories.session_runtime_leases.acquire(
            session_id=session.session_id,
            owner_id="worker:continuation-turn",
            mode="test",
            lease_seconds=60,
        )
        assert replacement.acquired is True

        with binding.context_factory(
            SandboxProcessHostAuthority(
                session_id=session.session_id,
                sandbox_workspace_id="sw_host_context",
                sandbox_run_id="srun_host_context",
                process_epoch=3,
            )
        ) as process_context:
            current = process_context.repositories.sessions.get(session.session_id)
            assert current is not None
            process_context.repositories.sessions.save(
                replace(current, objective="continued under sandbox-process authority")
            )

        with pytest.raises(RuntimeWriteFencingError, match="stale business write"):
            with binding.context_factory(stale_session_authority):
                pass

    with provider.read() as reader:
        saved = reader.repositories.sessions.get(session.session_id)
        assert saved is not None
        assert saved.objective == "continued under sandbox-process authority"


def test_v3_execution_engine_uses_configured_blank_world_roots(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bootstrap_client, foundation = _build_client(monkeypatch)
    del bootstrap_client
    provider = SQLiteRepositoryProvider(str(tmp_path / "control-plane.sqlite3"))
    sandbox_root = tmp_path / "sandboxes"
    blob_root = tmp_path / "blobs"
    dependencies = HostApiDependencies(
        foundation=foundation,
        v3_repository_provider=provider,
        v3_sandbox_workspace_root=sandbox_root,
        v3_artifact_blob_root=blob_root,
    )

    with provider.connection_scope() as owner:
        execution_engine = dependencies.build_v3_engine_registry(
            owner.repositories
        ).require("execution")
        session = Session.create(
            "sess_blank_world_roots",
            "proj_001",
            "Blank-world roots",
            "Keep direct provider artifacts inside the attempt blob root.",
        )
        owner.repositories.sessions.save(session)
        service = dependencies._build_v3_service(owner.repositories)
        context = service._build_runtime_context(session.session_id)

    assert execution_engine.sandbox_workspace_root == sandbox_root
    assert execution_engine.artifact_blob_root == blob_root
    assert service.sandbox_workspace_root == sandbox_root
    assert service.artifact_blob_root == blob_root
    assert context.sandbox_workspace_root == sandbox_root
    assert context.artifact_blob_root == blob_root


def test_v3_timed_out_callback_cannot_apply_late_business_effect(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bootstrap_client, foundation = _build_client(monkeypatch)
    del bootstrap_client
    provider = SQLiteRepositoryProvider(str(tmp_path / "late-effect-fence.sqlite3"))
    dependencies = HostApiDependencies(
        foundation=foundation,
        v3_repository_provider=provider,
    )
    session = Session.create(
        "sess_late_effect",
        "proj_001",
        "Late effect",
        "Preserve original state after timeout",
    )
    with provider.write() as owner:
        owner.repositories.sessions.save(session)
    with provider.connection_scope() as coordinator:
        acquired = coordinator.repositories.session_runtime_leases.acquire(
            session_id=session.session_id,
            owner_id="worker:timed-out-callback",
            mode="test",
            lease_seconds=60,
        )
        assert acquired.lease is not None
        execution_engine = dependencies.build_v3_engine_registry(
            coordinator.repositories,
            acquired.lease,
        ).require("execution")
        callback_scope = execution_engine.sandbox_host_call_context_factory
        assert callback_scope is not None
        callback_started = threading.Event()
        release_callback = threading.Event()
        callback_errors: list[BaseException] = []

        def return_late_after_timeout() -> None:
            try:
                with callback_scope(
                    session_id=session.session_id,
                    invocation_id="inv_late_callback",
                ) as callback_context:
                    callback_started.set()
                    assert release_callback.wait(timeout=5)
                    callback_context.repositories.sessions.save(
                        replace(session, objective="Late stale callback overwrite")
                    )
            except BaseException as exc:
                callback_errors.append(exc)

        callback = threading.Thread(target=return_late_after_timeout)
        callback.start()
        assert callback_started.wait(timeout=5)
        coordinator.connection.execute(
            "UPDATE session_runtime_leases SET expires_at = ? WHERE lease_token = ?",
            ("2020-01-01T00:00:00+00:00", acquired.lease.lease_token),
        )
        coordinator.connection.commit()
        replacement = coordinator.repositories.session_runtime_leases.acquire(
            session_id=session.session_id,
            owner_id="worker:replacement",
            mode="test",
            lease_seconds=60,
        )
        assert replacement.acquired is True
        release_callback.set()
        callback.join(timeout=5)

    assert not callback.is_alive()
    assert len(callback_errors) == 1
    assert isinstance(callback_errors[0], RuntimeWriteFencingError)
    with provider.read() as owner:
        assert owner.repositories.sessions.get(session.session_id) == session


class FakeExecutionAdapter:
    def submit_execution(
        self, session_id: str, payload: dict[str, object]
    ) -> ExecutionOutcome:
        del session_id, payload
        return ExecutionOutcome(
            run_id="run_001",
            status=RunStatus.SUCCEEDED,
            execution_mode="fixture_non_cutover",
            remote_run_dir="fixture://adapter/run_001",
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri="/tmp/stdout.log",
                    relative_path="stdout.log",
                    kind=ArtifactKind.LOG,
                ),
                ExecutionArtifactRef(
                    storage_uri="/tmp/result.json",
                    relative_path="result.json",
                    kind=ArtifactKind.RESULT,
                ),
            ),
            raw_result={
                "status": "fixture_non_cutover",
                "fixture": True,
                "synthetic_source": True,
                "cutover_eligible": False,
                "provider_status": "fixture_non_cutover",
                "tool_status": "fixture_non_cutover",
                "scientific_status": "fixture_non_cutover",
            },
        )


def _fixture_sandbox_runtime_identity() -> dict[str, str]:
    identity = {
        "configured_image_ref": "openzyme-pipeline-sandbox:test",
        "immutable_image_ref": "sha256:" + "a" * 64,
        "image_digest": "sha256:" + "a" * 64,
        "pipeline_sdk_digest": "sha256:" + "b" * 64,
        "sandbox_protocol_version": "test.v1",
    }
    identity["runtime_identity_digest"] = "sha256:" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return identity


class FixtureSandboxPreflight:
    ok = True
    message = "fixture sandbox is ready"
    runtime_identity = _fixture_sandbox_runtime_identity()


class FixtureNonCutoverPipelineSandboxRunner:
    def preflight(self) -> FixtureSandboxPreflight:
        return FixtureSandboxPreflight()

    def run_pipeline(
        self,
        *,
        session_id,
        invocation_id,
        code,
        inputs=(),
        control_handler=None,
        expected_runtime_identity=None,
    ):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome as SandboxOutcome

        del session_id, code, inputs
        assert expected_runtime_identity == _fixture_sandbox_runtime_identity()
        assert control_handler is not None
        workspace = dict(control_handler("hpc.workspace", {"label": "fpocket"}))
        structure = dict(
            control_handler(
                "hpc.stage_artifact",
                {
                    "hpc_workspace": workspace,
                    "artifact_id": "art_v3_structure",
                    "workspace_path": "inputs/structure.pdb",
                },
            )
        )
        run = dict(
            control_handler(
                "structure_tools.fpocket",
                {
                    "structure": structure,
                    "placement": workspace,
                    "expected_outputs": [
                        {
                            "path": "target_out",
                            "kind": "directory",
                            "format": "fpocket",
                        }
                    ],
                    "params": {},
                },
            )
        )
        control_handler(
            "hpc.fetch_outputs",
            {"hpc_workspace": workspace, "run_id": run["run_id"]},
        )
        return SandboxOutcome(
            run_id=f"sandbox_{invocation_id}",
            status=RunStatus.SUCCEEDED,
            execution_mode="fixture_non_cutover",
            remote_run_dir=f"fixture://sandbox/{invocation_id}",
            raw_result={
                "fixture": True,
                "synthetic_source": True,
                "cutover_eligible": False,
                "scientific_status": "fixture_non_cutover",
            },
            artifacts=(),
        )


class FakeResearchAdapter:
    def conduct(
        self, *, session_id: str, research_brief: str, unit: ResearchUnit
    ) -> ResearchUnitResult:
        del session_id, research_brief
        return self.normalize_search_response(
            unit=unit,
            response=self.web_search(
                query=unit.query,
                max_results=3,
                topic=unit.topic,
                include_raw_content=True,
            ),
        )

    def web_search(
        self,
        *,
        query: str,
        max_results: int = 3,
        topic: str = "general",
        include_raw_content: bool = True,
    ) -> dict[str, object]:
        del max_results, include_raw_content
        return {
            "results": [
                {
                    "title": f"Source for {topic}",
                    "url": f"https://example.org/{topic.replace(' ', '-')}",
                    "content": f"Finding for {query}",
                }
            ]
        }

    def fetch_url(
        self,
        *,
        url: str,
        query: str | None = None,
        extract_depth: str = "basic",
        format: str = "markdown",
        include_images: bool = False,
    ) -> dict[str, object]:
        del query, extract_depth, format, include_images
        return {
            "results": [
                {
                    "title": "Fetched source",
                    "url": url,
                    "raw_content": "Fetched content.",
                }
            ]
        }

    def normalize_search_response(
        self,
        *,
        unit: ResearchUnit,
        response: dict[str, object],
    ) -> ResearchUnitResult:
        results = list(response.get("results", []))
        result = dict(results[0]) if results else {}
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} supports the brief.",
            findings=(
                ResearchFinding(
                    summary=str(
                        result.get("content")
                        or result.get("raw_content")
                        or f"Finding for {unit.query}"
                    ),
                    query=unit.query,
                    confidence_label="high",
                    sources=(
                        ResearchSource(
                            title=f"Source for {unit.unit_id}",
                            locator=str(
                                result.get("url")
                                or f"https://example.org/{unit.unit_id}"
                            ),
                            kind=SourceRefKind.WEB_PAGE,
                        ),
                    ),
                ),
            ),
            unresolved_gaps=("Need structural follow-up",),
        )

    def normalize_fetch_response(
        self,
        *,
        url: str,
        query: str | None,
        response: dict[str, object],
    ) -> ResearchUnitResult:
        return self.normalize_search_response(
            unit=ResearchUnit(
                unit_id="web-fetch", topic="web fetch", query=query or url
            ),
            response=response,
        )


class FakeHarnessInvoker:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del system_prompt, messages, tools
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_task_create",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_llm_001",
                            "subject": "Capture design goals",
                            "description": "Extract the user goal into a tracked task.",
                            "kind": "general",
                            "priority": "high",
                        },
                    }
                ],
            }
        return {
            "content": "Created task task_llm_001 and captured the goal.",
            "tool_calls": [],
        }


class FakeHarnessModelFactory:
    def __init__(self) -> None:
        self.invokers: dict[str, FakeHarnessInvoker] = {}

    def create_tool_calling_invoker(self, *, purpose: str) -> FakeHarnessInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = FakeHarnessInvoker()
        return self.invokers[purpose]


class WorkflowFocusHarnessInvoker:
    def __init__(self, *, selected_ref: str, unselected_ref: str) -> None:
        self.selected_ref = selected_ref
        self.unselected_ref = unselected_ref
        self.calls = 0
        self.system_prompts: list[str] = []

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del messages, tools
        self.calls += 1
        self.system_prompts.append(system_prompt)
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_create_selected_workflow_task",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_selected_workflow",
                            "subject": "Delegate selected workflow",
                            "description": "The exact selected workflow may be delegated.",
                            "kind": "execution",
                        },
                    },
                    {
                        "id": "call_create_unselected_workflow_task",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_unselected_workflow",
                            "subject": "Reject unselected workflow",
                            "description": "An unselected workflow must remain unauthorized.",
                            "kind": "execution",
                        },
                    },
                ],
            }
        if self.calls == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_delegate_selected_workflow",
                        "name": "task.delegate",
                        "args": {
                            "task_id": "task_selected_workflow",
                            "agent_role": "executor",
                            "workflow_refs": [self.selected_ref],
                        },
                    },
                    {
                        "id": "call_delegate_unselected_workflow",
                        "name": "task.delegate",
                        "args": {
                            "task_id": "task_unselected_workflow",
                            "agent_role": "executor",
                            "workflow_refs": [self.unselected_ref],
                        },
                    },
                ],
            }
        return {"content": "Workflow authorization checked.", "tool_calls": []}


class WorkflowFocusHarnessModelFactory:
    def __init__(self, *, selected_ref: str, unselected_ref: str) -> None:
        self.invoker = WorkflowFocusHarnessInvoker(
            selected_ref=selected_ref,
            unselected_ref=unselected_ref,
        )

    def create_tool_calling_invoker(
        self, *, purpose: str
    ) -> WorkflowFocusHarnessInvoker:
        assert purpose == "v3_harness_loop"
        return self.invoker


class WorkflowFocusExecutionEngine:
    descriptor = EngineDescriptor(
        engine_name="execution",
        tool_names=(),
        input_schema={},
        output_schema={},
        requires_approval=True,
        supports_background=False,
        idempotency_key_shape="",
        produces_artifact_types=(),
        capability_key="execution",
    )

    def register_tools(self, registry: object) -> None:
        del registry


class FocusRecordingInvoker:
    def __init__(self, prompts: list[str]) -> None:
        self.prompts = prompts

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del messages, tools
        self.prompts.append(system_prompt)
        return {"content": "Focus observed.", "tool_calls": []}


class FocusRecordingModelFactory:
    context_window_tokens = 100_000

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def create_tool_calling_invoker(self, *, purpose: str) -> FocusRecordingInvoker:
        assert purpose == "v3_harness_loop"
        return FocusRecordingInvoker(self.prompts)


class BlockingHarnessInvoker(FakeHarnessInvoker):
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        super().__init__()
        self.entered = entered
        self.release = release

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        self.entered.set()
        assert self.release.wait(timeout=5)
        return super().invoke_with_tools(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
        )


class BlockingHarnessModelFactory:
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        self.invoker = BlockingHarnessInvoker(entered, release)

    def create_tool_calling_invoker(self, *, purpose: str) -> BlockingHarnessInvoker:
        assert purpose == "v3_harness_loop"
        return self.invoker


class PressureHarnessInvoker:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "tools": list(tools),
            }
        )
        if not self.responses:
            return {"content": "pressure test complete", "tool_calls": []}
        return self.responses.pop(0)


class PressureHarnessModelFactory:
    def __init__(
        self,
        responses: list[dict[str, object]],
        *,
        model: str = "pressure-test-model",
        context_window_tokens: int | None = 100_000,
        default_output_tokens: int | None = 0,
    ) -> None:
        self.model = model
        self.context_window_tokens = context_window_tokens
        self.default_output_tokens = default_output_tokens
        self.invokers: dict[str, PressureHarnessInvoker] = {}
        self._responses = list(responses)

    def create_tool_calling_invoker(self, *, purpose: str) -> PressureHarnessInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = PressureHarnessInvoker(self._responses)
        return self.invokers[purpose]


class FakePhaseBStructuredInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose

    def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict[str, object]):
        del system_prompt
        objective = str(user_payload.get("objective") or "Improve thermostability")
        if self.purpose == "intake_collect":
            return IntakePhaseOutput(
                clarification=IntakeClarification(),
                constraint_set=ConstraintSet(
                    objective_summary=objective,
                    constraints=[
                        ConstraintItem(
                            category="technical",
                            description="Prepare an execution-ready design workspace.",
                        )
                    ],
                ),
                design_brief=DesignBriefDraft(
                    design_brief=f"Design brief for {objective}",
                    success_criteria=["Prepare execution-ready artifacts."],
                ),
                research_brief=RuntimeResearchBriefDraft(
                    research_brief=f"Research brief for {objective}",
                    focus_areas=["evidence"],
                    expected_outputs=["research summary"],
                ),
            )
        if self.purpose == "design_next_action":
            evidence_refs = list(user_payload.get("evidence_refs") or [])
            run_summary = dict(user_payload.get("run_summary") or {})
            if not evidence_refs:
                return DesignNextAction(
                    action_kind="collect_research",
                    summary="Collect evidence for the design objective.",
                    rationale="No canonical evidence exists yet.",
                    arguments={},
                )
            if not run_summary:
                return DesignNextAction(
                    action_kind="request_execution",
                    summary="Route the curated workspace into execution.",
                    rationale="Evidence and execution-ready artifacts are available.",
                    arguments={},
                )
            return DesignNextAction(
                action_kind="stop",
                summary="Package the completed design dossier.",
                rationale="Research, workspace curation, and execution are complete.",
                stop_reason="design_loop_complete",
                arguments={},
            )
        if self.purpose == "deep_research_brief":
            return EngineResearchBriefDraft(research_brief=f"Research brief for {objective}")
        if self.purpose == "deep_research_supervisor":
            unit_results = list(user_payload.get("unit_results") or [])
            if any(result.get("findings") for result in unit_results):
                return ResearchSupervisorAction(
                    action_kind="complete",
                    rationale="A usable finding exists.",
                )
            return ResearchSupervisorAction(
                action_kind="conduct_research",
                rationale="Collect one evidence unit.",
                unit_plan=EngineResearchUnitPlan(
                    units=[
                        EngineResearchUnitDraft(
                            unit_id="evidence",
                            topic="supporting evidence",
                            query=f"{objective} evidence",
                            rationale="Collect evidence for downstream design.",
                        )
                    ],
                    synthesis_goal="Support downstream design.",
                ),
            )
        if self.purpose == "deep_research_synthesis":
            return EvidenceSynthesis(
                summary="Research evidence supports the current objective.",
                evidence_items=[
                    EvidenceSynthesisItem(
                        summary="Evidence supports the current scaffold direction.",
                        query=f"{objective} evidence",
                        confidence_label="high",
                        sources=[
                            ResearchSourceItem(
                                title="Synthetic source",
                                locator="https://example.org/evidence",
                                kind="web_page",
                            )
                        ],
                    ),
                    EvidenceSynthesisItem(
                        summary="Structure-backed evidence supports execution.",
                        query=f"{objective} structure evidence",
                        confidence_label="medium",
                        sources=[
                            ResearchSourceItem(
                                title="Synthetic structure source",
                                locator="https://example.org/structure-evidence",
                                kind="web_page",
                            )
                        ],
                    ),
                ],
                unresolved_gaps=["Need wet-lab validation."],
            )
        if self.purpose == "execution_plan":
            return ExecutionPlanDraft(
                catalog_tool_id="fpocket",
                rationale="Use the curated execution-ready structure artifact.",
                tool_inputs={},
                expected_result_summary="Run fpocket on the selected structure artifact.",
            )
        if self.purpose == "report_review":
            return ReportDraft(
                title="OpenZyme design report",
                summary="Objective Improve thermostability completed with research, execution, and report outputs.",
                stage_summary="Research summary: evidence was collected and execution results were recorded.",
                key_decisions=["Proceed with the current scaffold direction."],
            )
        raise AssertionError(f"Unhandled structured purpose {self.purpose!r}")


class FakePhaseBToolCallingInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del system_prompt, messages, tools
        self.calls += 1
        if self.purpose == "deep_research_researcher" and self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_web_search",
                        "name": "web.search",
                        "args": {
                            "query": "thermostability evidence",
                            "topic": "general",
                            "max_results": 1,
                        },
                    }
                ],
            }
        return {"content": "", "tool_calls": []}


class FakePhaseBModelFactory:
    def __init__(self) -> None:
        self.tool_invokers: dict[str, FakePhaseBToolCallingInvoker] = {}

    def create_structured_invoker(self, *, purpose: str) -> FakePhaseBStructuredInvoker:
        return FakePhaseBStructuredInvoker(purpose)

    def create_tool_calling_invoker(self, *, purpose: str):
        if purpose.startswith("v3_"):
            return FakeHarnessInvoker()
        if purpose not in self.tool_invokers:
            self.tool_invokers[purpose] = FakePhaseBToolCallingInvoker(purpose)
        return self.tool_invokers[purpose]


class FakeEchoHarnessInvoker:
    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del system_prompt, messages, tools
        return {"content": "Planning started.", "tool_calls": []}


class FakeEchoHarnessModelFactory:
    def create_tool_calling_invoker(self, *, purpose: str) -> FakeEchoHarnessInvoker:
        assert purpose.startswith("v3_")
        return FakeEchoHarnessInvoker()


class BlockingTraceInvoker:
    def __init__(
        self, entered_second_call: threading.Event, release_second_call: threading.Event
    ) -> None:
        self.calls = 0
        self.entered_second_call = entered_second_call
        self.release_second_call = release_second_call

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del system_prompt, messages, tools
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "I will create a task before answering.",
                "tool_calls": [
                    {
                        "id": "call_task_create",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_realtime_trace",
                            "subject": "Realtime trace task",
                            "description": "Exercise realtime trace streaming.",
                        },
                    }
                ],
            }
        self.entered_second_call.set()
        assert self.release_second_call.wait(timeout=5)
        return {"content": "Task created.", "tool_calls": []}


class BlockingTraceModelFactory:
    def __init__(self) -> None:
        self.entered_second_call = threading.Event()
        self.release_second_call = threading.Event()
        self.invoker = BlockingTraceInvoker(
            self.entered_second_call, self.release_second_call
        )

    def create_tool_calling_invoker(self, *, purpose: str) -> BlockingTraceInvoker:
        assert purpose == "v3_harness_loop"
        return self.invoker


class DebugRecordingModelFactory:
    def create_tool_calling_invoker(
        self, *, purpose: str
    ) -> LangChainToolCallingInvoker:
        class _Runnable:
            def invoke(self, messages):
                return {
                    "content": "Debug response.",
                    "tool_calls": [],
                    "message_count": len(messages),
                }

        class _Model:
            def bind_tools(self, tools):
                return _Runnable()

        return LangChainToolCallingInvoker(
            model=_Model(),
            purpose=purpose,
            model_name="debug-model",
            base_url="https://debug.example/v1",
        )


def _message_role(message: object) -> str | None:
    if isinstance(message, dict):
        return None if message.get("role") is None else str(message["role"])
    message_type = type(message).__name__
    if message_type == "HumanMessage":
        return "user"
    if message_type == "AIMessage":
        return "assistant"
    if message_type == "ToolMessage":
        return "tool"
    return None


def _message_content(message: object) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _tool_message_name(message: object) -> str | None:
    if isinstance(message, dict):
        return None if message.get("name") is None else str(message["name"])
    return (
        None
        if getattr(message, "name", None) is None
        else str(getattr(message, "name"))
    )


def _tool_message_payload(message: object) -> dict[str, object]:
    try:
        envelope = json.loads(_message_content(message))
    except json.JSONDecodeError:
        return {}
    payload = envelope.get("payload")
    return payload if isinstance(payload, dict) else {}


def _created_code_artifact_id(messages: list[object]) -> str | None:
    for message in reversed(messages):
        if _tool_message_name(message) != "artifact.create_text":
            continue
        payload = _tool_message_payload(message)
        artifact = payload.get("artifact")
        if isinstance(artifact, dict) and artifact.get("artifact_id"):
            return str(artifact["artifact_id"])
    return None


class FakeEngineHarnessInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0
        self.system_prompts: list[str] = []
        self.report_delegated = False

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del tools
        self.calls += 1
        self.system_prompts.append(system_prompt)
        if self.purpose == "v3_teammate_loop:researcher":
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_research_start",
                            "name": "deep_research.start",
                            "args": {
                                "task_id": "task_research_v3",
                                "brief": "Collect papers for the scaffold family.",
                            },
                        }
                    ],
                }
            if self.calls == 2:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_research_task_complete",
                            "name": "task.finish",
                            "args": {
                                "task_id": "task_research_v3",
                                "status": "completed",
                                "summary": "Research complete.",
                            },
                        }
                    ],
                }
            return {"content": "Research complete.", "tool_calls": []}
        if self.purpose == "v3_teammate_loop:executor":
            if any(_tool_message_name(message) == "task.finish" for message in messages):
                return {
                    "content": "fpocket found 1 pocket(s) for the selected artifact set. Output artifacts: run_inv_pipeline_task_execution_v3:target_out.",
                    "tool_calls": [],
                }
            if any(
                _tool_message_name(message) == "execution.pipeline.status"
                for message in messages
            ):
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_execution_task_complete",
                            "name": "task.finish",
                            "args": {
                                "task_id": "task_execution_v3",
                                "status": "completed",
                                "summary": "fpocket found 1 pocket for the selected artifact set.",
                            },
                        }
                    ],
                }
            code_artifact_id = _created_code_artifact_id(messages)
            if code_artifact_id is not None and not any(
                _tool_message_name(message) == "execution.pipeline.start"
                for message in messages
            ):
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_execution_start",
                            "name": "execution.pipeline.start",
                            "args": {
                                "task_id": "task_execution_v3",
                                "code_artifact_id": code_artifact_id,
                                "inputs": {
                                    "artifact_ids": ["art_v3_structure"],
                                },
                            },
                        }
                    ],
                }
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_execution_source",
                            "name": "artifact.create_text",
                            "args": {
                                "filename": "fpocket_pipeline.py",
                                "content": (
                                    "from openzyme_pipeline import artifacts, hpc, structure_tools\n"
                                    "structure = artifacts.get('art_v3_structure')\n"
                                    "ws = hpc.workspace('fpocket')\n"
                                    "remote_structure = ws.stage_artifact(structure['artifact_id'], workspace_path='inputs/structure.pdb')\n"
                                    "run = structure_tools.fpocket(structure=remote_structure, placement=ws, expected_outputs=[{'path': 'target_out', 'kind': 'directory', 'format': 'fpocket'}])\n"
                                    "ws.fetch_outputs(run)\n"
                                ),
                            },
                        }
                    ],
                }
            if "Existing execution pipeline invocation:" in system_prompt:
                invocation_id = (
                    system_prompt.split("Existing execution pipeline invocation:", 1)[1]
                    .split(".", 1)[0]
                    .strip()
                )
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_execution_status",
                            "name": "execution.pipeline.status",
                            "args": {"invocation_id": invocation_id},
                        }
                    ],
                }
            return {
                "content": "Execution started and is waiting for approval.",
                "tool_calls": [],
            }
        if self.purpose == "v3_teammate_loop:reporter":
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_report_draft_update",
                            "name": "report_draft.update",
                            "args": {
                                "task_id": "task_report_v3",
                                "title": "Workspace report",
                                "summary": "Integrated workspace report",
                                "status": "ready",
                                "markdown": "# Workspace report\n\nIntegrated workspace report",
                            },
                        }
                    ],
                }
            if self.calls == 2:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_report_publish",
                            "name": "report.publish",
                            "args": {
                                "task_id": "task_report_v3",
                                "title": "Workspace report",
                                "summary": "Integrated workspace report",
                                "stage_summary": "Research and execution summarized.",
                            },
                        }
                    ],
                }
            if self.calls == 3:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_report_task_complete",
                            "name": "task.finish",
                            "args": {
                                "task_id": "task_report_v3",
                                "status": "completed",
                                "summary": "Reporting complete.",
                            },
                        }
                    ],
                }
            return {"content": "Reporting complete.", "tool_calls": []}
        focused_task = next(
            (
                line.removeprefix("Focused task: ").strip()
                for line in system_prompt.splitlines()
                if line.startswith("Focused task: ")
            ),
            "none",
        )
        latest_tool_name = None
        seen_tool_names: list[str] = []
        for message in messages:
            if _message_role(message) != "tool":
                continue
            tool_name = _tool_message_name(message)
            if tool_name is None:
                continue
            latest_tool_name = tool_name
            seen_tool_names.append(tool_name)
        latest_user_message = next(
            (
                _message_content(message)
                for message in reversed(messages)
                if _message_role(message) == "user"
            ),
            "",
        )
        if (
            focused_task == "task_research_v3"
            and "completed task_id=task_research_v3" in system_prompt
            and latest_tool_name is None
        ):
            return {"content": "Research complete.", "tool_calls": []}
        if (
            focused_task == "task_execution_v3"
            and "completed task_id=task_execution_v3" in system_prompt
            and latest_tool_name is None
        ):
            return {
                "content": "fpocket found 1 pocket(s) for the selected artifact set. Output artifacts: run_inv_pipeline_task_execution_v3:target_out.",
                "tool_calls": [],
            }
        if (
            focused_task == "task_report_v3"
            and "completed task_id=task_report_v3" in system_prompt
            and latest_tool_name is None
        ):
            return {"content": "Reporting complete.", "tool_calls": []}
        if focused_task == "task_research_v3":
            if latest_tool_name is None:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_delegate_research",
                            "name": "task.delegate",
                            "args": {
                                "task_id": focused_task,
                                "agent_role": "researcher",
                                "instructions": "Collect papers for the scaffold family.",
                            },
                        },
                    ],
                }
            return {
                "content": "Delegated research task task_research_v3.",
                "tool_calls": [],
            }

        if focused_task == "task_execution_v3":
            if latest_tool_name is None:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_delegate_execution",
                            "name": "task.delegate",
                            "args": {
                                "task_id": focused_task,
                                "agent_role": "executor",
                                "instructions": "Run fpocket against the candidate structure.",
                            },
                        },
                    ],
                }
            return {
                "content": "Delegated execution task task_execution_v3.",
                "tool_calls": [],
            }

        if focused_task == "task_report_v3":
            if not self.report_delegated:
                self.report_delegated = True
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_delegate_report",
                            "name": "task.delegate",
                            "args": {
                                "task_id": focused_task,
                                "agent_role": "reporter",
                                "instructions": "Produce a concise report for the completed V3 workspace.",
                            },
                        },
                    ],
                }
            return {
                "content": "Delegated reporting task task_report_v3.",
                "tool_calls": [],
            }

        if "Please track extracting the design goals as a task." in latest_user_message:
            if latest_tool_name is None:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_task_create",
                            "name": "task.create",
                            "args": {
                                "task_id": "task_llm_001",
                                "subject": "Capture design goals",
                                "description": "Extract the user goal into a tracked task.",
                                "kind": "general",
                                "priority": "high",
                            },
                        }
                    ],
                }
            return {
                "content": "Created task task_llm_001 and captured the goal.",
                "tool_calls": [],
            }

        raise AssertionError(
            f"Unhandled fake harness request for focused task {focused_task!r}"
        )


class FakeEngineHarnessModelFactory:
    def __init__(self) -> None:
        self.invokers: dict[str, FakeEngineHarnessInvoker] = {}
        self.fallback_factory = FakePhaseBModelFactory()

    def create_structured_invoker(self, *, purpose: str) -> FakePhaseBStructuredInvoker:
        return self.fallback_factory.create_structured_invoker(purpose=purpose)

    def create_tool_calling_invoker(self, *, purpose: str):
        if not purpose.startswith("v3_"):
            return self.fallback_factory.create_tool_calling_invoker(purpose=purpose)
        if purpose not in self.invokers:
            self.invokers[purpose] = FakeEngineHarnessInvoker(purpose)
        return self.invokers[purpose]


class DiagnosticExecutorInvoker:
    def __init__(self) -> None:
        self.calls = 0
        self.system_prompts: list[str] = []

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del tools
        self.calls += 1
        self.system_prompts.append(system_prompt)
        assert "sanitized failure evidence" in system_prompt
        assert "INPUT_OR_ENTRYPOINT_MISSING" in system_prompt
        if any(_tool_message_name(message) == "task.finish" for message in messages):
            return {
                "content": (
                    "The approved fpocket task failed at the HPC runner boundary; "
                    "I marked the execution task failed with the runner evidence."
                ),
                "tool_calls": [],
            }
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_mark_failed",
                    "name": "task.finish",
                    "args": {
                        "task_id": "task_hpc_diag",
                        "status": "failed",
                        "summary": "Approved fpocket failed at the HPC runner boundary.",
                        "failure_summary": (
                            "Approved fpocket reached the HPC runner, but the runner failed "
                            "with INPUT_OR_ENTRYPOINT_MISSING while creating the Apptainer container."
                        ),
                        "failure_ref": "engine:inv_hpc_diag",
                    },
                }
            ],
        }


class DiagnosticExecutorModelFactory:
    def __init__(self) -> None:
        self.invoker = DiagnosticExecutorInvoker()
        self.master_calls = 0

    def create_tool_calling_invoker(self, *, purpose: str):
        if purpose == "v3_harness_loop":
            factory = self

            class _MasterInvoker:
                def invoke_with_tools(
                    self,
                    *,
                    system_prompt: str,
                    messages: list[object],
                    tools: list[object],
                ) -> dict[str, object]:
                    del system_prompt, messages, tools
                    factory.master_calls += 1
                    return {
                        "content": (
                            "The approved fpocket task failed at the HPC runner boundary. "
                            "The execution task is marked failed with failure_ref engine:inv_hpc_diag."
                        ),
                        "tool_calls": [],
                    }

            return _MasterInvoker()
        assert purpose == "v3_teammate_loop:executor"
        return self.invoker


class FailedHpcExecutionEngine:
    def __init__(self, repositories: CoreRepositories) -> None:
        self.repositories = repositories

    @property
    def descriptor(self) -> EngineDescriptor:
        return EngineDescriptor(
            engine_name="execution",
            tool_names=("execution.pipeline.start", "execution.pipeline.status"),
            input_schema={},
            output_schema={},
            requires_approval=True,
            supports_background=False,
            idempotency_key_shape="test",
            produces_artifact_types=(),
            capability_key="execution",
        )

    def register_tools(self, registry: object) -> None:
        del registry

    def continue_after_approval(
        self, *, invocation_id: str, resolution: str
    ) -> ExecutionStartResult:
        del resolution
        invocation = self.repositories.invocations.get(invocation_id)
        assert invocation is not None
        output_ref = "eng_out_failed_hpc"
        error = {
            "type": "hpc_operation_failed",
            "message": "Pipeline failed: Traceback (most recent call last):",
            "hint": "Inspect the HPC run or runner configuration.",
            "stderr_excerpt": "PipelineSdkError: structure_tools.fpocket failed with status failed",
            "hpc_failure": {
                "run_id": "run_failed_hpc",
                "runner_run_id": "runner_failed_hpc",
                "status": "failed",
                "execution_mode": "ssh",
                "exit_code": 255,
                "error_code": "INPUT_OR_ENTRYPOINT_MISSING",
                "stderr_excerpt": "FATAL: container creation failed: mount source does not exist",
            },
        }
        now = "2026-05-03T16:00:00+00:00"
        self.repositories.engine_documents.save(
            EngineDocumentRecord(
                document_id=output_ref,
                session_id=invocation.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="execution_result",
                payload={
                    "pipeline": {
                        "sandbox_status": "failed",
                        "terminal_summary": "Pipeline failed.",
                        "error": error,
                    }
                },
                created_at=now,
                updated_at=now,
            )
        )
        failed = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=EngineInvocationStatus.FAILED,
            input_ref=invocation.input_ref,
            output_ref=output_ref,
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=now,
        )
        self.repositories.invocations.save(failed)
        return ExecutionStartResult(
            invocation=failed,
            run=None,
            approval=None,
            parsed_result=ExecutionParsedResult(
                result_summary="Pipeline failed.",
                structured_findings={"error": error},
            ),
        )


def _build_client(
    monkeypatch, *, with_model_factory: bool = True
) -> tuple[TestClient, RuntimeFoundation]:
    del monkeypatch
    foundation = RuntimeFoundation(
        execution_adapter=FakeExecutionAdapter(),
        hpc_catalog_provider=RepoBackedHpcCatalogProvider(),
        hpc_execution_registry=DefaultHpcExecutionRegistry(
            RepoBackedHpcCatalogProvider()
        ),
        research_adapter=FakeResearchAdapter(),
        model_factory=FakePhaseBModelFactory() if with_model_factory else None,
    )
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=foundation,
                    security_policy=_local_test_security(),
                )
            )
        ),
        foundation,
    )


def _build_v3_llm_client(monkeypatch) -> tuple[TestClient, RuntimeFoundation]:
    client, foundation = _build_client(monkeypatch)
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=replace(
                        foundation, model_factory=FakeHarnessModelFactory()
                    ),
                    v3_background_runtime_enabled=False,
                )
            )
        ),
        foundation,
    )


def _build_v3_engine_llm_client(
    monkeypatch,
) -> tuple[TestClient, CoreRepositories, FakeEngineHarnessModelFactory]:
    client, foundation = _build_client(monkeypatch)
    del client
    owner = tempfile.TemporaryDirectory(prefix="openzyme-engine-test-")
    provider = SQLiteRepositoryProvider(str(Path(owner.name) / "control-plane.sqlite3"))
    model_factory = FakeEngineHarnessModelFactory()
    command_client = TestClient(
        create_app(
            HostApiDependencies(
                foundation=replace(foundation, model_factory=model_factory),
                v3_repository_provider=provider,
                v3_pipeline_sandbox_runner=FixtureNonCutoverPipelineSandboxRunner(),
                v3_background_runtime_enabled=False,
            )
        )
    )
    repositories = _provider_backed_test_repositories(
        command_client,
        provider,
        owner,
    )
    return command_client, repositories, model_factory


def _build_v3_engine_repositories() -> CoreRepositories:
    # Explicit legacy fixture: a few pure unit tests inspect one in-memory
    # repository from both the TestClient and assertion threads. Production Host
    # composition always uses SQLiteRepositoryProvider with thread-affine scopes.
    connection = connect_v3_sqlite(":memory:", check_same_thread=False)
    apply_v3_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def test_scientific_transition_finalizer_reports_nonretryable_host_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _build_v3_engine_repositories()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        scientific_workflow_contract_registry=(
            AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY
        ),
    )
    session_id = "sess_scientific_finalizer_failure"
    lane_id = "lane_scientific_finalizer_failure"
    task_id = "task_scientific_finalizer_failure"
    agent_id = "agent:scientific-finalizer"
    service.create_session(
        project_id="proj_scientific_finalizer_failure",
        session_id=session_id,
        title="Scientific finalizer",
        objective="Return Host finalization failure to the responsible agent.",
    )
    service.create_lane(
        {
            "session_id": session_id,
            "lane_id": lane_id,
            "name": "formal",
            "cwd": "/workspace",
        }
    )
    service.create_task(
        {
            "session_id": session_id,
            "task_id": task_id,
            "subject": "Run one authorized attempt",
            "lane_id": lane_id,
            "assigned_ref": agent_id,
        }
    )
    service.claim_lane(lane_id, claimed_ref=agent_id)
    now = "2026-07-23T00:00:00+00:00"
    repositories.agents.save(
        AgentMember(
            agent_id=agent_id,
            session_id=session_id,
            lane_id=lane_id,
            task_id=task_id,
            name="scientific-finalizer",
            role="executor",
            status=AgentMemberStatus.ACTIVE,
            parent_agent_id="agent:master",
            created_at=now,
            updated_at=now,
            runtime_state="idle",
        )
    )
    granted = service.grant_scientific_attempt_authorization(
        {
            "task_id": task_id,
            "campaign_id": "campaign_scientific_finalizer",
            "workflow_id": "aox_blank_world",
            "root_ref": "attempts/scientific-finalizer",
            "allowed_scopes": ["formal"],
            "allowed_effect_classes": ["provider", "hpc"],
            "allowed_providers": ["provider:test"],
            "allowed_hpc_targets": ["hpc:test"],
            "max_attempts": 1,
            "max_micu": 100,
            "max_cost_microunits": 1_000,
            "max_wall_time_seconds": 600,
            "expires_at": "2099-01-01T00:00:00+00:00",
        },
        session_id=session_id,
        grantor_ref="user:operator",
        idempotency_key="grant-scientific-finalizer",
    )
    envelope_id = granted["record"]["envelope_id"]
    control = service.scientific_attempt_control()
    first = control.request_authorized_attempt_admission(
        envelope_id=envelope_id,
        session_id=session_id,
        task_id=task_id,
        actor_ref=agent_id,
        idempotency_key="attempt-request-first",
    )
    first_request_id = first.admission_request_id
    second = control.request_authorized_attempt_admission(
        envelope_id=envelope_id,
        session_id=session_id,
        task_id=task_id,
        actor_ref=agent_id,
        idempotency_key="attempt-request-second",
    )
    second_request_id = second.admission_request_id

    with monkeypatch.context() as patch:
        patch.setattr(
            V3EventStore,
            "append",
            lambda _store, _session_id, _events: (_ for _ in ()).throw(
                RuntimeError("injected transition event failure")
            ),
        )
        with pytest.raises(
            RuntimeError,
            match="injected transition event failure",
        ):
            service.finalize_pending_scientific_transitions(
                session_id=session_id
            )

    assert repositories.scientific_attempts.list_by_session(session_id) == []
    assert [
        event
        for event in service.event_store.list(session_id)
        if event["event_type"].startswith("scientific.attempt.")
    ] == []
    assert repositories.runtime_signals.list_by_session(session_id) == []

    # Simulate an older Host/crash boundary where Core committed the transition
    # but no durable event or wakeup was written.  Pending finalization must
    # reconcile delivery instead of skipping the already-admitted request.
    service.scientific_attempt_control().finalize_attempt_admission(
        admission_request_id=first_request_id
    )
    assert repositories.scientific_attempts.list_by_session(session_id)
    assert [
        event
        for event in service.event_store.list(session_id)
        if event["event_type"].startswith("scientific.attempt.")
    ] == []
    assert repositories.runtime_signals.list_by_session(session_id) == []

    events = service.finalize_pending_scientific_transitions(
        session_id=session_id
    )

    assert {event["event_type"] for event in events} >= {
        "scientific.attempt.admitted",
        "scientific.transition.failed",
    }
    observations = repositories.failure_observations.list_by_source(
        session_id=session_id,
        source_kind="scientific_transition",
        source_ref=second_request_id,
    )
    assert len(observations) == 1
    assert observations[0].error_code == "authorization_exhausted"
    assert observations[0].recoverability.value == "authorization_required"
    assert observations[0].actor_kind.value == "system"
    assert observations[0].agent_id == agent_id
    admitted_event = next(
        event
        for event in events
        if event["event_type"] == "scientific.attempt.admitted"
    )
    admitted_id = str(admitted_event["payload"]["record_id"])
    transition_signals = [
        signal
        for signal in repositories.runtime_signals.list_by_session(session_id)
        if signal.source_ref == admitted_id
    ]
    assert len(transition_signals) == 1
    assert service.finalize_pending_scientific_transitions(
        session_id=session_id
    ) == []
    assert len(
        [
            signal
            for signal in repositories.runtime_signals.list_by_session(
                session_id
            )
            if signal.source_ref == admitted_id
        ]
    ) == 1
    assert len(
        repositories.failure_observations.list_by_source(
            session_id=session_id,
            source_kind="scientific_transition",
            source_ref=second_request_id,
        )
    ) == 1

    captured_instructions: list[str] = []

    def run_teammate(runtime_context, **kwargs):
        captured_instructions.append(str(kwargs["instructions"]))
        return HarnessResult(
            session_id=session_id,
            status=HarnessStatus.COMPLETED,
            snapshot=SessionRuntimeSnapshot.load(
                runtime_context.repositories,
                session_id,
            ),
            events=(),
            outputs=("Canonical transition facts observed.",),
            tool_results=(),
        )

    monkeypatch.setattr(agent_runtime_module, "run_teammate_loop", run_teammate)
    service.model_factory = object()
    failure_id = observations[0].failure_id
    source_ids = (admitted_id, failure_id)
    runtime_outcomes = []
    with MutationScopeService(repositories).writer_turn(
        session_id=session_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="fixture:production-transition-wakes",
    ):
        for source_id in source_ids:
            signal = next(
                item
                for item in repositories.runtime_signals.list_by_session(
                    session_id
                )
                if item.source_ref == source_id
            )
            runtime_outcomes.append(
                AgentRuntimeService(
                    service._build_runtime_context(
                        session_id,
                        task_id=task_id,
                        lane_id=lane_id,
                    )
                ).wake_agent(signal, max_steps=1)
            )

    assert all(outcome.ok for outcome in runtime_outcomes)
    assert len(captured_instructions) == 2
    admitted_facts = json.loads(
        captured_instructions[0]
        .splitlines()[0]
        .removeprefix("Canonical wake facts: ")
    )
    failure_facts = json.loads(
        captured_instructions[1]
        .splitlines()[0]
        .removeprefix("Canonical wake facts: ")
    )
    assert admitted_facts["source_kind"] == "scientific_attempt_admitted"
    assert admitted_facts["attempt_id"] == admitted_id
    assert failure_facts["source_kind"] == "failure_observation"
    assert failure_facts["failure_id"] == failure_id
    assert failure_facts["error_code"] == "authorization_exhausted"
    assert failure_facts["recoverability"] == "authorization_required"
    assert failure_facts["effect_certainty"] == "no_effect"
    assert failure_facts["retry_eligibility"] == "terminal"
    assert failure_facts["facts_key_count"] > 0
    assert failure_facts["facts_digest"].startswith("sha256:")
    assert all(
        instructions.index("Canonical wake facts: ")
        < instructions.index(f"Task {task_id}:")
        for instructions in captured_instructions
    )


def _build_v3_pressure_client(
    monkeypatch,
    model_factory: PressureHarnessModelFactory,
) -> tuple[TestClient, CoreRepositories, PressureHarnessModelFactory]:
    client, foundation = _build_client(monkeypatch)
    del client
    owner = tempfile.TemporaryDirectory(prefix="openzyme-pressure-test-")
    provider = SQLiteRepositoryProvider(str(Path(owner.name) / "control-plane.sqlite3"))
    command_client = TestClient(
        create_app(
            HostApiDependencies(
                foundation=replace(foundation, model_factory=model_factory),
                v3_repository_provider=provider,
                v3_background_runtime_enabled=False,
            )
        )
    )
    repositories = _provider_backed_test_repositories(
        command_client,
        provider,
        owner,
    )
    return command_client, repositories, model_factory


def _clear_context_budget_env(monkeypatch) -> None:
    for name in (
        "OPENZYME_LLM_CONTEXT_WINDOW_TOKENS",
        "OPENZYME_LLM_DEFAULT_OUTPUT_TOKENS",
        "OPENZYME_LLM_CONTEXT_WARN_RATIO",
        "OPENZYME_LLM_CONTEXT_AUTO_COMPACT_RATIO",
        "OPENZYME_LLM_CONTEXT_EMERGENCY_RATIO",
    ):
        monkeypatch.delenv(name, raising=False)


def _seed_large_text_artifact(
    repositories: CoreRepositories,
    session_id: str,
    tmp_path: Path,
) -> str:
    line = "stress-observation-" + ("x" * 720)
    content = "\n".join(f"{index:03d}:{line}" for index in range(500)) + "\n"
    path = tmp_path / "large_tool_source.txt"
    path.write_text(content, encoding="utf-8")
    artifact_id = "art_pressure_large_text"
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact_id,
            session_id=session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.LOG,
            storage_uri=str(path),
            relative_path="large_tool_source.txt",
            title="large_tool_source.txt",
            description="Large text artifact used by the pressure conversation.",
            metadata={
                "source": "pressure_test",
                "format": "txt",
                "content_digest": f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
            },
            created_at="2026-06-04T10:00:00+00:00",
        )
    )
    return artifact_id


def _wait_for_background_runtime(
    client: TestClient,
    *,
    min_processed: int = 1,
    timeout_seconds: float = 3.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    status: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get("/debug/v3-runtime")
        assert response.status_code == 200
        status = response.json()
        if int(status.get("processed_signal_count") or 0) >= min_processed:
            return status
        time.sleep(0.05)
    return status


def _wait_for_v3_background_workspace(
    client: TestClient,
    *,
    session_id: str,
    is_ready,
    repositories: CoreRepositories | None = None,
    timeout_seconds: float = 30.0,
) -> tuple[dict[str, object], str, dict[str, object], list[str]]:
    deadline = time.monotonic() + timeout_seconds
    workspace: dict[str, object] = {}
    event_text = ""
    runtime_status: dict[str, object] = {}
    resolved_approvals: list[str] = []
    while time.monotonic() < deadline:
        workspace_response = client.get(f"/v3/sessions/{session_id}/workspace")
        if workspace_response.status_code != 200:
            runtime_response = client.get("/debug/v3-runtime")
            assert workspace_response.status_code == 200, {
                "step": "get_v3_workspace",
                "body": workspace_response.text,
                "workspace": workspace,
                "runtime_status": runtime_response.json()
                if runtime_response.status_code == 200
                else runtime_response.text,
                "events": event_text[-1000:],
                "signals": []
                if repositories is None
                else [
                    signal.to_dict()
                    for signal in repositories.runtime_signals.list_by_session(
                        session_id
                    )
                ],
            }
        workspace = workspace_response.json()
        runtime_response = client.get("/debug/v3-runtime")
        assert runtime_response.status_code == 200
        runtime_status = runtime_response.json()

        pending_approvals = workspace.get("pending_approvals") or []
        if pending_approvals:
            approval_id = pending_approvals[0]["approval_id"]
            resolved = client.post(
                f"/v3/approvals/{approval_id}/resolve",
                json={"decision": "approved"},
            )
            assert resolved.status_code == 200, resolved.text
            resolved_approvals.append(approval_id)
            time.sleep(0.2)
            continue

        if is_ready(workspace, event_text, runtime_status):
            while time.monotonic() < deadline:
                events_response = client.get(
                    f"/v3/sessions/{session_id}/events?replay=1"
                )
                if events_response.status_code == 200:
                    event_text = events_response.text
                    return workspace, event_text, runtime_status, resolved_approvals
                assert events_response.status_code == 200, {
                    "step": "get_v3_events",
                    "body": events_response.text,
                    "workspace": workspace,
                    "runtime_status": runtime_status,
                    "signals": []
                    if repositories is None
                    else [
                        signal.to_dict()
                        for signal in repositories.runtime_signals.list_by_session(
                            session_id
                        )
                    ],
                }
        time.sleep(0.2)
    raise AssertionError(
        {
            "tasks": [
                item["task"]
                for item in (workspace.get("task_board") or {}).get("items", [])
            ],
            "pending_approvals": workspace.get("pending_approvals"),
            "capabilities": {
                key: [item.get("status") for item in value]
                for key, value in (workspace.get("capabilities") or {}).items()
            },
            "runtime_status": runtime_status,
            "resolved_approvals": resolved_approvals,
            "signals": []
            if repositories is None
            else [
                signal.to_dict()
                for signal in repositories.runtime_signals.list_by_session(session_id)
            ],
        }
    )


def test_v3_task_crud_does_not_implicitly_drain_agent_runtime() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_task_crud_no_drain",
            "proj_001",
            "Task CRUD",
            "Keep task mutation separate from runtime scheduling.",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:researcher:crud",
            session_id="sess_task_crud_no_drain",
            lane_id=None,
            task_id=None,
            name="Ada",
            role="researcher",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-05-03T15:59:00+00:00",
            updated_at="2026-05-03T15:59:00+00:00",
            runtime_state="idle",
            current_correlation_id=None,
        )
    )
    model_factory = FakeEngineHarnessModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )

    created = service.create_task(
        {
            "session_id": "sess_task_crud_no_drain",
            "task_id": "task_no_drain",
            "subject": "Collect evidence",
            "description": "Ready research task.",
            "kind": "research",
        }
    )
    updated = service.update_task(
        "task_no_drain",
        {"description": "Still only a task mutation."},
    )

    assert created["task"]["status"] == "todo"
    assert updated["task"]["status"] == "todo"
    assert model_factory.invokers == {}
    assert repositories.runtime_signals.list_by_session("sess_task_crud_no_drain") == []


def test_v3_task_crud_rejects_business_exit_statuses(monkeypatch) -> None:
    client, _ = _build_client(monkeypatch, with_model_factory=False)
    created_session = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_task_exit_guard",
            "project_id": "proj_001",
            "objective": "Guard task business exits",
        },
    )
    assert created_session.status_code == 200

    for status in ("blocked", "completed", "failed", "cancelled"):
        rejected_create = client.post(
            "/v3/tasks",
            json={
                "session_id": "sess_task_exit_guard",
                "task_id": f"task_create_{status}",
                "subject": status,
                "status": status,
            },
        )
        assert rejected_create.status_code == 422
        assert rejected_create.json()["error"]["code"] == "request_validation_error"

    created_task = client.post(
        "/v3/tasks",
        json={
            "session_id": "sess_task_exit_guard",
            "task_id": "task_edit_exit_guard",
            "subject": "Edit guard",
        },
    )
    assert created_task.status_code == 200
    for status in ("blocked", "completed", "failed", "cancelled"):
        rejected_update = client.patch(
            "/v3/tasks/task_edit_exit_guard",
            json={"status": status},
        )
        assert rejected_update.status_code == 422
        assert rejected_update.json()["error"]["code"] == "request_validation_error"


def test_v3_drain_runtime_does_not_auto_claim_by_default() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_drain_no_auto_claim",
            "proj_001",
            "Drain",
            "Do not auto-claim ready tasks by default.",
        )
    )
    repositories.tasks.save(
        Task.create(
            "task_ready_no_auto_claim",
            "sess_drain_no_auto_claim",
            "Collect evidence",
            "Ready research task.",
            kind="research",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:researcher:no_auto_claim",
            session_id="sess_drain_no_auto_claim",
            lane_id=None,
            task_id=None,
            name="Ada",
            role="researcher",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-05-03T15:59:00+00:00",
            updated_at="2026-05-03T15:59:00+00:00",
            runtime_state="idle",
            current_correlation_id=None,
        )
    )
    service = V3HostApiService(repositories=repositories, event_store=V3EventStore())

    service.drain_runtime(session_id="sess_drain_no_auto_claim")

    assert repositories.runtime_signals.list_by_session("sess_drain_no_auto_claim") == []


def test_v3_drain_runtime_explicit_auto_claim_still_enqueues_ready_task() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_drain_auto_claim",
            "proj_001",
            "Drain",
            "Explicitly auto-claim ready tasks.",
        )
    )
    repositories.tasks.save(
        Task.create(
            "task_ready_auto_claim",
            "sess_drain_auto_claim",
            "Collect evidence",
            "Ready research task.",
            kind="research",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:researcher:auto_claim",
            session_id="sess_drain_auto_claim",
            lane_id=None,
            task_id=None,
            name="Curie",
            role="researcher",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-05-03T15:59:00+00:00",
            updated_at="2026-05-03T15:59:00+00:00",
            runtime_state="idle",
            current_correlation_id=None,
        )
    )
    service = V3HostApiService(repositories=repositories, event_store=V3EventStore())

    service.drain_runtime(
        session_id="sess_drain_auto_claim",
        auto_enqueue_ready_tasks=True,
    )

    signals = repositories.runtime_signals.list_by_session("sess_drain_auto_claim")
    assert len(signals) == 1
    assert signals[0].task_id == "task_ready_auto_claim"
    assert signals[0].reason.value == "task_available"


def test_v3_drain_runtime_uses_configured_scheduler_limits(monkeypatch) -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_drain_limits",
            "proj_001",
            "Drain limits",
            "Use configured scheduler limits.",
        )
    )
    captured: dict[str, object] = {}

    class FakeScheduler:
        def __init__(self, context, **kwargs):
            captured["context"] = context
            captured.update(kwargs)

        def run_once_sync(
            self,
            session_id: str,
            *,
            max_signals: int,
            max_steps_per_agent: int,
            signal_ids=None,
            auto_enqueue_ready_tasks: bool = False,
        ):
            captured["session_id"] = session_id
            captured["max_signals"] = max_signals
            captured["max_steps_per_agent"] = max_steps_per_agent
            captured["signal_ids"] = signal_ids
            captured["auto_enqueue_ready_tasks"] = auto_enqueue_ready_tasks
            return ()

    monkeypatch.setattr("openzyme_host_api.v3_service.AgentRuntimeScheduler", FakeScheduler)
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        scheduler_limits={"global": 7, "session": 5, "agent": 3},
    )

    service.drain_runtime(
        session_id="sess_drain_limits",
        max_signals=4,
        max_steps_per_agent=6,
    )

    assert captured["worker_id"] == "host-api:runtime-drain"
    assert captured["max_global_concurrency"] == 7
    assert captured["max_session_concurrency"] == 5
    assert captured["max_agent_concurrency"] == 3
    assert captured["runtime_mode"] == "manual_drain"
    assert captured["max_signals"] == 4
    assert captured["max_steps_per_agent"] == 6
    assert captured["auto_enqueue_ready_tasks"] is False


def test_v3_manual_drain_returns_locked_when_background_owns_session() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_manual_locked_by_background",
            "proj_001",
            "Runtime lock",
            "Manual drain must respect background ownership.",
        )
    )
    lease = repositories.session_runtime_leases.acquire(
        session_id="sess_manual_locked_by_background",
        owner_id="host-api:background-runtime",
        mode="background",
        lease_seconds=60,
    ).lease
    assert lease is not None
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=object(),
    )

    result = service.drain_runtime(session_id="sess_manual_locked_by_background")

    assert result.status == "locked"
    assert result.outputs == ()
    assert result.events[0]["event_type"] == "runtime.session_locked"
    assert result.events[0]["payload"]["status"] == "locked"
    assert result.events[0]["payload"]["retry_after_seconds"] > 0
    assert "owner_id" not in result.events[0]["payload"]
    assert "mode" not in result.events[0]["payload"]
    assert "fencing_token" not in result.events[0]["payload"]
    assert repositories.session_runtime_leases.get_active(
        "sess_manual_locked_by_background"
    ).lease_token == lease.lease_token


def test_v3_background_runtime_skips_when_manual_drain_owns_session() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_background_locked_by_manual",
            "proj_001",
            "Runtime lock",
            "Background runtime must respect manual ownership.",
        )
    )
    repositories.session_runtime_leases.acquire(
        session_id="sess_background_locked_by_manual",
        owner_id="host-api:runtime-drain",
        mode="manual_drain",
        lease_seconds=60,
    )
    event_store = V3EventStore()
    service = V3HostApiService(
        repositories=repositories,
        event_store=event_store,
        model_factory=object(),
    )

    outcomes = asyncio.run(
        service.run_background_runtime_once(
            session_id="sess_background_locked_by_manual",
            worker_id="host-api:background-runtime",
        )
    )

    assert outcomes == []
    events = event_store.list("sess_background_locked_by_manual")
    assert [event["event_type"] for event in events] == ["runtime.session_locked"]
    assert events[0]["payload"]["status"] == "locked"
    assert events[0]["payload"]["retry_after_seconds"] > 0
    assert "owner_id" not in events[0]["payload"]
    assert "mode" not in events[0]["payload"]
    assert "fencing_token" not in events[0]["payload"]


def test_v3_session_runtime_lease_does_not_block_other_sessions() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create("sess_locked_a", "proj_001", "A", "A")
    )
    repositories.sessions.save(
        Session.create("sess_unlocked_b", "proj_001", "B", "B")
    )
    repositories.session_runtime_leases.acquire(
        session_id="sess_locked_a",
        owner_id="host-api:background-runtime",
        mode="background",
        lease_seconds=60,
    )
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=object(),
    )

    result = service.drain_runtime(session_id="sess_unlocked_b")

    assert result.status == "completed"
    assert repositories.session_runtime_leases.get_active("sess_locked_a") is not None
    assert repositories.session_runtime_leases.get_active("sess_unlocked_b") is None


def test_v3_drain_runtime_request_defaults_disable_auto_claim() -> None:
    assert DrainV3RuntimeRequest().auto_enqueue_ready_tasks is False


def test_v3_post_message_request_has_no_max_steps_field() -> None:
    assert "max_steps" not in PostV3MessageRequest.model_fields
    assert "max_steps" not in PostV3MessageRequest.model_json_schema()["properties"]


def test_v3_post_message_only_enqueues_master_signal() -> None:
    repositories = _build_v3_engine_repositories()
    model_factory = FakeHarnessModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        objective="Queue the master.",
        session_id="sess_msg_enqueue",
    )

    result = service.post_message(
        session_id="sess_msg_enqueue",
        message="Start planning.",
    )

    assert result.status == "completed"
    assert result.outputs == ()
    assert model_factory.invokers == {}
    assert repositories.agents.get("sess_msg_enqueue", "agent:master") is not None
    messages = repositories.inbox.list_by_session("sess_msg_enqueue")
    assert [message.message_type for message in messages] == ["user_message"]
    signals = repositories.runtime_signals.list_by_session("sess_msg_enqueue")
    assert len(signals) == 1
    assert signals[0].agent_id == "agent:master"
    assert signals[0].reason.value == "inbox_unread"
    assert signals[0].status.value == "pending"


def test_v3_message_skill_focus_survives_explicit_drain_without_expanding_authority() -> (
    None
):
    repositories = _build_v3_engine_repositories()
    workflow_refs = {
        manifest.workflow_id: manifest.selection_ref
        for manifest in default_workflow_registry().list_manifests()
    }
    selected_ref = workflow_refs["aox-hmm-live"]
    unselected_ref = workflow_refs["generic-sandbox-execution"]
    model_factory = WorkflowFocusHarnessModelFactory(
        selected_ref=selected_ref,
        unselected_ref=unselected_ref,
    )
    engine_registry = EngineRegistry()
    engine_registry.register(WorkflowFocusExecutionEngine())
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        engine_registry=engine_registry,
        model_factory=model_factory,
    )
    service.create_session(
        session_id="sess_durable_workflow_focus",
        project_id="proj_001",
        objective="Preserve exact workflow authority across admission.",
    )

    admitted = service.post_message(
        session_id="sess_durable_workflow_focus",
        message="Delegate only the explicitly selected workflow.",
        skill_keys=(selected_ref, selected_ref),
    )
    assert admitted.status == "completed"
    source_message = repositories.inbox.list_by_session(
        "sess_durable_workflow_focus"
    )[0]
    source_document = repositories.engine_documents.get(
        str(source_message.payload_ref)
    )
    assert source_document is not None
    assert source_document.payload["skill_keys"] == [selected_ref]

    drained = service.drain_runtime(
        session_id="sess_durable_workflow_focus",
        max_signals=1,
    )

    tool_events = {
        event["payload"]["call_id"]: event["payload"]
        for event in drained.events
        if event["event_type"] == "tool.completed"
    }
    assert tool_events["call_delegate_selected_workflow"]["ok"] is True
    assert (
        tool_events["call_delegate_unselected_workflow"]["error_code"]
        == "workflow_ref_not_authorized"
    )
    selected_task = repositories.tasks.get("task_selected_workflow")
    unselected_task = repositories.tasks.get("task_unselected_workflow")
    assert selected_task is not None and selected_task.assigned_ref is not None
    assert unselected_task is not None and unselected_task.assigned_ref is None
    assert "# Explicitly selected workflow knowledge pack" in (
        model_factory.invoker.system_prompts[0]
    )


def test_v3_master_fails_closed_before_provider_on_corrupt_user_focus_source() -> (
    None
):
    repositories = _build_v3_engine_repositories()
    model_factory = FakeHarnessModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        objective="Reject a corrupt user-message authority source.",
        session_id="sess_corrupt_workflow_focus",
    )
    service.post_message(
        session_id="sess_corrupt_workflow_focus",
        message="This message source will be corrupted before drain.",
        skill_keys=("skill:explicit",),
    )
    source_message = repositories.inbox.list_by_session(
        "sess_corrupt_workflow_focus"
    )[0]
    source_document = repositories.engine_documents.get(
        str(source_message.payload_ref)
    )
    assert source_document is not None
    repositories.engine_documents.save(
        replace(source_document, document_kind="delegation_request")
    )

    drained = service.drain_runtime(
        session_id="sess_corrupt_workflow_focus",
        max_signals=1,
    )

    assert drained.status == "failed"
    assert model_factory.invokers == {}
    signals = repositories.runtime_signals.list_by_session(
        "sess_corrupt_workflow_focus"
    )
    assert len(signals) == 1
    assert signals[0].status.value == "failed"
    assert repositories.tasks.list_by_session("sess_corrupt_workflow_focus") == []
    assert repositories.agents.list_by_session("sess_corrupt_workflow_focus") == [
        repositories.agents.get("sess_corrupt_workflow_focus", "agent:master")
    ]


def test_v3_master_accepts_legacy_user_conversation_without_skill_keys() -> None:
    repositories = _build_v3_engine_repositories()
    workflow_ref = next(
        manifest.selection_ref
        for manifest in default_workflow_registry().list_manifests()
        if manifest.workflow_id == "aox-hmm-live"
    )
    model_factory = FocusRecordingModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        objective="Read a legacy canonical conversation document.",
        session_id="sess_legacy_workflow_focus",
    )
    service.post_message(
        session_id="sess_legacy_workflow_focus",
        message="This canonical message predates durable workflow focus.",
        skill_keys=(workflow_ref,),
    )
    source_message = repositories.inbox.list_by_session(
        "sess_legacy_workflow_focus"
    )[0]
    source_document = repositories.engine_documents.get(
        str(source_message.payload_ref)
    )
    assert source_document is not None
    legacy_payload = dict(source_document.payload)
    legacy_payload.pop("skill_keys")
    repositories.engine_documents.save(
        replace(source_document, payload=legacy_payload)
    )

    drained = service.drain_runtime(
        session_id="sess_legacy_workflow_focus",
        max_signals=1,
    )

    assert drained.status == "completed"
    assert len(model_factory.prompts) == 1
    assert "# Explicitly selected workflow knowledge pack" not in (
        model_factory.prompts[0]
    )


def test_v3_master_restores_each_user_message_focus_without_sticky_union() -> None:
    repositories = _build_v3_engine_repositories()
    workflow_refs = {
        manifest.workflow_id: manifest.selection_ref
        for manifest in default_workflow_registry().list_manifests()
    }
    aox_ref = workflow_refs["aox-hmm-live"]
    generic_ref = workflow_refs["generic-sandbox-execution"]
    model_factory = FocusRecordingModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        objective="Keep workflow focus scoped to each source message.",
        session_id="sess_nonsticky_workflow_focus",
    )
    service.post_message(
        session_id="sess_nonsticky_workflow_focus",
        message="Use the AOX workflow for this turn.",
        skill_keys=(aox_ref,),
    )
    service.post_message(
        session_id="sess_nonsticky_workflow_focus",
        message="Use only the generic workflow for this turn.",
        skill_keys=(generic_ref,),
    )

    drained = service.drain_runtime(
        session_id="sess_nonsticky_workflow_focus",
        max_signals=2,
    )

    assert drained.status == "completed"
    assert len(model_factory.prompts) == 2
    assert "workflow_id: aox-hmm-live" in model_factory.prompts[0]
    assert "workflow_id: generic-sandbox-execution" not in model_factory.prompts[0]
    assert "workflow_id: generic-sandbox-execution" in model_factory.prompts[1]
    assert "workflow_id: aox-hmm-live" not in model_factory.prompts[1]


def test_v3_master_protocol_inbox_does_not_grant_workflow_authority() -> None:
    repositories = _build_v3_engine_repositories()
    workflow_ref = next(
        manifest.selection_ref
        for manifest in default_workflow_registry().list_manifests()
        if manifest.workflow_id == "aox-hmm-live"
    )
    model_factory = FocusRecordingModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        objective="Keep protocol payloads outside workflow authority.",
        session_id="sess_protocol_without_workflow_focus",
    )
    protocol = ProtocolService(repositories)
    payload_ref = protocol.persist_payload(
        session_id="sess_protocol_without_workflow_focus",
        document_kind="protocol_message",
        payload={"skill_keys": [workflow_ref]},
    )
    protocol.send_message(
        session_id="sess_protocol_without_workflow_focus",
        sender="harness",
        sender_kind=InboxParticipantKind.HARNESS,
        recipient="agent:master",
        recipient_kind=InboxParticipantKind.AGENT,
        message_type="user_message",
        payload_ref=payload_ref,
    )

    drained = service.drain_runtime(
        session_id="sess_protocol_without_workflow_focus",
        max_signals=1,
    )

    assert drained.status == "completed"
    assert len(model_factory.prompts) == 1
    assert "# Explicitly selected workflow knowledge pack" not in (
        model_factory.prompts[0]
    )


def test_v3_background_runtime_processes_message_without_manual_drain(
    monkeypatch,
) -> None:
    client, foundation = _build_client(monkeypatch)
    del client
    dependencies = HostApiDependencies(
        foundation=replace(foundation, model_factory=FakeHarnessModelFactory()),
        security_policy=_local_test_security(),
        v3_background_runtime_enabled=True,
    )
    app = create_app(dependencies)
    with TestClient(app) as background_client:
        created = background_client.post(
            "/v3/sessions",
            json={
                "session_id": "sess_bg_runtime",
                "project_id": "proj_001",
                "objective": "Capture the user's design goal",
            },
        )
        assert created.status_code == 200

        message = background_client.post(
            "/v3/sessions/sess_bg_runtime/messages",
            json={"message": "Please track extracting the design goals as a task."},
        )
        assert message.status_code == 200
        assert message.json()["outputs"] == []

        status = _wait_for_background_runtime(background_client)

        assert status["running"] is True
        assert status["worker_id"] == "host-api:background-runtime"
        workspace = background_client.get(
            "/v3/sessions/sess_bg_runtime/workspace"
        ).json()
        assert (
            workspace["conversation"][1]["content"]
            == "Created task task_llm_001 and captured the goal."
        )
        with dependencies.v3_repository_scope(mode="read") as repositories:
            signals = [
                signal.to_dict()
                for signal in repositories.runtime_signals.list_by_session(
                    "sess_bg_runtime"
                )
            ]
        assert signals[0]["status"] == "completed"
        assert signals[0]["claimed_by"] == "host-api:background-runtime"


def test_v3_background_runtime_tick_does_not_block_event_loop() -> None:
    order: list[str] = []

    class FakeRuntimeSignals:
        def list_claimable_session_ids(self) -> list[str]:
            return ["sess_bg_runtime"]

    class FakeRepositories:
        runtime_signals = FakeRuntimeSignals()

    class BlockingService:
        repositories = FakeRepositories()
        model_factory = object()

        async def run_background_runtime_once(
            self,
            *,
            session_id: str,
            worker_id: str,
            max_signals: int,
            max_steps_per_agent: int,
        ) -> list[dict[str, object]]:
            assert session_id == "sess_bg_runtime"
            assert worker_id == "host-api:background-runtime"
            assert max_signals == 3
            assert max_steps_per_agent == 8
            time.sleep(0.2)
            order.append("runtime_done")
            return [{"status": "completed"}]

    async def run_check() -> None:
        service = V3BackgroundRuntimeService(
            build_service=BlockingService,
            notifier=RuntimeSignalNotifier(),
            enabled=True,
        )

        async def heartbeat() -> None:
            await asyncio.sleep(0.05)
            order.append("event_loop_alive")

        await asyncio.gather(service.run_tick(), heartbeat())

    asyncio.run(run_check())

    assert order == ["event_loop_alive", "runtime_done"]


def test_v3_durable_work_supervisor_is_bounded_and_nonblocking() -> None:
    order: list[str] = []

    class FakeOutcome:
        execution_id = "exec_fixture"
        action = "dispatch"
        semantic_progress = True
        lifecycle_state = "waiting_external"
        state_version = 3
        effect_certainty = "effect_known"
        retry_eligibility = "verify_then_retry"

    class BlockingWorker:
        def run_once(self) -> FakeOutcome:
            time.sleep(0.2)
            order.append("durable_done")
            return FakeOutcome()

    worker_ids: list[str] = []

    def worker_factory(worker_id: str) -> BlockingWorker:
        worker_ids.append(worker_id)
        return BlockingWorker()

    async def run_check() -> None:
        notifier = RuntimeSignalNotifier()
        supervisor = V3DurableWorkSupervisor(
            worker_factory=worker_factory,  # type: ignore[arg-type]
            notifier=notifier,
            enabled=True,
            max_concurrency=1,
        )

        async def heartbeat() -> None:
            await asyncio.sleep(0.05)
            order.append("event_loop_alive")

        outcomes, _ = await asyncio.gather(supervisor.run_tick(), heartbeat())
        assert len(outcomes) == 1
        assert outcomes[0]["execution_id"] == "exec_fixture"
        assert outcomes[0]["semantic_progress"] is True
        assert supervisor.status()["processed_count"] == 1
        assert notifier.notify_count == 1

    asyncio.run(run_check())

    assert order == ["event_loop_alive", "durable_done"]
    assert worker_ids == ["host-api:durable-work:0"]


@pytest.mark.parametrize("action", ("claim_raced", "not_claimable"))
def test_v3_durable_work_coordinator_retains_non_idle_no_progress(
    action: str,
) -> None:
    class FakeOutcome:
        semantic_progress = False

        def __init__(self, outcome_action: str) -> None:
            self.action = outcome_action

    class FakeWorker:
        def __init__(self, outcome_action: str) -> None:
            self.outcome_action = outcome_action

        def run_once(self) -> FakeOutcome:
            return FakeOutcome(self.outcome_action)

    coordinator = V3DurableWorkCoordinator(
        workers=(FakeWorker(action), FakeWorker("idle"))
    )

    outcome = coordinator.run_once()

    assert outcome.action == action
    assert outcome.semantic_progress is False


def test_v3_durable_work_supervisor_defers_database_busy_without_counting_progress() -> None:
    class BusyOutcome:
        execution_id = "exec_database_busy"
        action = "database_busy"
        semantic_progress = False
        lifecycle_state = None
        state_version = None
        effect_certainty = None
        retry_eligibility = None

    class BusyWorker:
        def run_once(self) -> BusyOutcome:
            return BusyOutcome()

    async def run_check() -> None:
        supervisor = V3DurableWorkSupervisor(
            worker_factory=lambda worker_id: BusyWorker(),  # type: ignore[arg-type]
            notifier=RuntimeSignalNotifier(),
            enabled=True,
            max_concurrency=1,
        )

        outcomes = await supervisor.run_tick()
        status = supervisor.status()

        assert outcomes[0]["action"] == "database_busy"
        assert outcomes[0]["semantic_progress"] is False
        assert status["processed_count"] == 0
        assert status["database_busy_count"] == 1
        assert status["last_error"] == "durable database busy; retry deferred"

    asyncio.run(run_check())


def test_v3_durable_work_supervisor_retains_no_progress_without_self_wakeup() -> (
    None
):
    class NoProgressOutcome:
        execution_id = "exec_waiting"
        action = "poll"
        semantic_progress = False
        lifecycle_state = "waiting_external"
        state_version = 7
        effect_certainty = "effect_known"
        retry_eligibility = "verify_then_retry"

    class NoProgressWorker:
        def run_once(self) -> NoProgressOutcome:
            return NoProgressOutcome()

    async def run_check() -> None:
        notifier = RuntimeSignalNotifier()
        supervisor = V3DurableWorkSupervisor(
            worker_factory=lambda worker_id: NoProgressWorker(),  # type: ignore[arg-type]
            notifier=notifier,
            enabled=True,
            max_concurrency=1,
        )

        outcomes = await supervisor.run_tick()
        status = supervisor.status()

        assert outcomes == (
            {
                "execution_id": "exec_waiting",
                "action": "poll",
                "semantic_progress": False,
                "lifecycle_state": "waiting_external",
                "state_version": 7,
                "effect_certainty": "effect_known",
                "retry_eligibility": "verify_then_retry",
            },
        )
        assert status["processed_count"] == 0
        assert status["last_outcomes"] == list(outcomes)
        assert notifier.notify_count == 0

    asyncio.run(run_check())


def test_v3_durable_work_supervisor_rejects_untyped_progress_contract() -> None:
    class MissingProgressOutcome:
        execution_id = "exec_missing_progress"
        action = "dispatch"

    class InvalidProgressOutcome:
        execution_id = "exec_invalid_progress"
        action = "dispatch"
        semantic_progress = 1

    class FixtureWorker:
        def __init__(self, outcome: object) -> None:
            self.outcome = outcome

        def run_once(self) -> object:
            return self.outcome

    async def run_check(outcome: object) -> None:
        notifier = RuntimeSignalNotifier()
        supervisor = V3DurableWorkSupervisor(
            worker_factory=lambda worker_id: FixtureWorker(outcome),
            notifier=notifier,
            enabled=True,
            max_concurrency=1,
        )

        assert await supervisor.run_tick() == ()
        assert supervisor.status()["processed_count"] == 0
        assert "typed semantic_progress" in str(supervisor.status()["last_error"])
        assert notifier.notify_count == 0

    asyncio.run(run_check(MissingProgressOutcome()))
    asyncio.run(run_check(InvalidProgressOutcome()))


def test_v3_durable_work_supervisor_stops_claims_and_accounts_for_late_worker() -> None:
    started = threading.Event()
    release = threading.Event()
    worker_ids: list[str] = []

    class LateOutcome:
        execution_id = "exec_late_shutdown"
        action = "poll"
        semantic_progress = False
        lifecycle_state = "waiting_external"
        state_version = 4
        effect_certainty = "effect_known"
        retry_eligibility = "verify_then_retry"

    class LateWorker:
        def run_once(self) -> LateOutcome:
            started.set()
            release.wait(timeout=2)
            return LateOutcome()

    def worker_factory(worker_id: str) -> LateWorker:
        worker_ids.append(worker_id)
        return LateWorker()

    async def run_check() -> None:
        supervisor = V3DurableWorkSupervisor(
            worker_factory=worker_factory,  # type: ignore[arg-type]
            notifier=RuntimeSignalNotifier(wake_delay_seconds=0.001),
            enabled=True,
            max_concurrency=1,
            shutdown_timeout_seconds=0.05,
        )
        supervisor.start()
        assert await asyncio.to_thread(started.wait, 1)

        await supervisor.stop()
        timed_out = supervisor.status()

        assert timed_out["accepting_work"] is False
        assert timed_out["active_worker_count"] == 1
        assert timed_out["shutdown_incomplete"] is True
        assert await supervisor.run_tick() == ()

        release.set()
        for _ in range(20):
            if supervisor.status()["active_worker_count"] == 0:
                break
            await asyncio.sleep(0.01)
        retired = supervisor.status()
        assert retired["active_worker_count"] == 0
        assert retired["shutdown_incomplete"] is False

    asyncio.run(run_check())

    assert worker_ids == ["host-api:durable-work:0"]


def test_v3_durable_rollback_stops_admission_but_retains_active_drain_capability(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    foundation = build_local_eval_foundation()
    foundation = replace(
        foundation,
        settings=replace(
            foundation.settings,
            reliability=ReliabilityRefactorSettings(),
        ),
    )
    dependencies = HostApiDependencies(
        foundation=foundation,
        v3_legacy_repositories_for_tests=_build_v3_engine_repositories(),
    )
    active_route = "bio.ncbi_fetch_proteins.provider:v1"
    monkeypatch.setattr(
        HostApiDependencies,
        "active_v3_durable_route_ids",
        lambda self: (active_route,),
    )
    monkeypatch.setattr(
        HostApiDependencies,
        "active_v3_durable_execution_count",
        lambda self: 1,
    )

    adapters = dependencies.build_v3_durable_route_adapters()
    supervisor = _build_durable_work_supervisor(dependencies)

    assert active_route in adapters
    assert supervisor.enabled is True
    dependencies.v3_durable_work_enabled = False
    with pytest.raises(RuntimeError, match="durable admission or active rows exist"):
        _build_durable_work_supervisor(dependencies)


def test_v3_background_runtime_once_releases_operation_lock_while_scheduler_runs() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session(
            session_id="sess_bg_lock",
            project_id="proj_001",
            title="Background lock",
            objective="Exercise runtime lock release.",
            status=SessionStatus.ACTIVE,
            created_at="2026-05-31T00:00:00+00:00",
            updated_at="2026-05-31T00:00:00+00:00",
        )
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    class Outcome:
        def to_dict(self) -> dict[str, object]:
            return {"status": "completed"}

    class BlockingScheduler:
        async def run_once(
            self,
            session_id: str,
            *,
            max_signals: int,
            max_steps_per_agent: int,
        ) -> list[Outcome]:
            assert session_id == "sess_bg_lock"
            assert max_signals == 1
            assert max_steps_per_agent == 1
            entered.set()
            await release.wait()
            return [Outcome()]

    class LockAwareService(V3HostApiService):
        def _build_scheduler(self, context, *, worker_id, runtime_mode="manual_drain"):
            del context, worker_id, runtime_mode
            return BlockingScheduler()

    service = LockAwareService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=object(),
    )

    async def run_check() -> None:
        task = asyncio.create_task(
            service.run_background_runtime_once(
                session_id="sess_bg_lock",
                max_signals=1,
                max_steps_per_agent=1,
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        acquired = service.operation_lock.acquire(blocking=False)
        assert acquired is True
        service.operation_lock.release()
        release.set()
        assert await task == [{"status": "completed"}]

    asyncio.run(run_check())


def test_v3_drain_runtime_releases_operation_lock_while_scheduler_runs() -> None:
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session(
            session_id="sess_drain_lock",
            project_id="proj_001",
            title="Drain lock",
            objective="Exercise drain lock release.",
            status=SessionStatus.ACTIVE,
            created_at="2026-05-31T00:00:00+00:00",
            updated_at="2026-05-31T00:00:00+00:00",
        )
    )
    entered = threading.Event()
    release = threading.Event()
    result_holder: dict[str, object] = {}

    class LockAwareService(V3HostApiService):
        def _drain_pending_agent_signals(self, *args, **kwargs):
            del args, kwargs
            entered.set()
            assert release.wait(timeout=2)
            return []

    service = LockAwareService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=object(),
    )

    def run_drain() -> None:
        result_holder["result"] = service.drain_runtime(
            session_id="sess_drain_lock",
            max_signals=1,
            max_steps_per_agent=1,
        )

    thread = threading.Thread(target=run_drain)
    thread.start()
    assert entered.wait(timeout=1)
    acquired = service.operation_lock.acquire(blocking=False)
    assert acquired is True
    service.operation_lock.release()
    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    result = result_holder["result"]
    assert result.status == "completed"


def test_v3_blocking_provider_does_not_hold_sqlite_write_transaction(
    monkeypatch,
) -> None:
    client, foundation = _build_client(monkeypatch)
    del client
    entered = threading.Event()
    release = threading.Event()
    dependencies = HostApiDependencies(
        foundation=replace(
            foundation,
            model_factory=BlockingHarnessModelFactory(entered, release),
        ),
        v3_background_runtime_enabled=False,
    )
    drain_result: dict[str, object] = {}
    write_result: dict[str, object] = {}

    with TestClient(create_app(dependencies)) as scoped_client:
        assert scoped_client.post(
            "/v3/sessions",
            json={
                "session_id": "sess_provider_blocked",
                "project_id": "proj_001",
                "objective": "Block inside the provider.",
            },
        ).status_code == 200
        assert scoped_client.post(
            "/v3/sessions/sess_provider_blocked/messages",
            json={"message": "Track this request."},
        ).status_code == 200

        drain_thread = threading.Thread(
            target=lambda: drain_result.setdefault(
                "response",
                _admit_and_observe_runtime_command(
                    scoped_client,
                    session_id="sess_provider_blocked",
                ),
            )
        )
        drain_thread.start()
        assert entered.wait(timeout=2)

        write_thread = threading.Thread(
            target=lambda: write_result.setdefault(
                "response",
                scoped_client.post(
                    "/v3/sessions",
                    json={
                        "session_id": "sess_concurrent_short_write",
                        "project_id": "proj_001",
                        "objective": "Must commit while the provider is blocked.",
                    },
                ),
            )
        )
        write_thread.start()
        write_thread.join(timeout=1)
        write_completed_before_provider_release = not write_thread.is_alive()
        release.set()
        write_thread.join(timeout=5)
        drain_thread.join(timeout=5)

    assert write_completed_before_provider_release is True
    assert not write_thread.is_alive()
    assert not drain_thread.is_alive()
    assert write_result["response"].status_code == 200
    assert drain_result["response"].status_code == 202


def test_v3_background_runtime_runs_teammate_and_master_followup_without_manual_drain(
    monkeypatch,
    tmp_path: Path,
    request,
) -> None:
    client, foundation = _build_client(monkeypatch)
    del client
    repository_provider = SQLiteRepositoryProvider(
        str(tmp_path / "background-runtime.sqlite3")
    )
    repository_scope = repository_provider.connection_scope()
    v3_repositories = repository_scope.__enter__().repositories
    request.addfinalizer(
        lambda: repository_scope.__exit__(None, None, None)
    )
    model_factory = FakeEngineHarnessModelFactory()
    dependencies = HostApiDependencies(
        foundation=replace(foundation, model_factory=model_factory),
        security_policy=_local_test_security(),
        v3_repository_provider=repository_provider,
        v3_background_runtime_enabled=True,
        v3_pipeline_sandbox_runner=FixtureNonCutoverPipelineSandboxRunner(),
    )
    app = create_app(dependencies)
    with TestClient(app) as background_client:
        created = background_client.post(
            "/v3/sessions",
            json={
                "session_id": "sess_bg_v3_engines",
                "project_id": "proj_001",
                "objective": "Evaluate a thermostability candidate and publish the final report",
            },
        )
        assert created.status_code == 200
        _seed_v3_execution_artifact(
            v3_repositories,
            "sess_bg_v3_engines",
            tmp_path=tmp_path,
        )
        lane = background_client.post(
            "/v3/lanes",
            json={
                "session_id": "sess_bg_v3_engines",
                "lane_id": "lane_bg_v3_engines",
                "name": "background engine lane",
                "cwd": "/tmp/openzyme-bg-v3-engines",
            },
        )
        assert lane.status_code == 200

        research_task = background_client.post(
            "/v3/tasks",
            json={
                "session_id": "sess_bg_v3_engines",
                "task_id": "task_research_v3",
                "subject": "Collect evidence",
                "description": "Collect papers for the scaffold family.",
                "kind": "research",
                "lane_id": "lane_bg_v3_engines",
            },
        )
        assert research_task.status_code == 200
        research = background_client.post(
            "/v3/sessions/sess_bg_v3_engines/messages",
            json={"message": "Run the research task.", "task_id": "task_research_v3"},
        )
        assert research.status_code == 200
        assert research.json()["outputs"] == []
        assert "v3_teammate_loop:researcher" not in model_factory.invokers

        research_workspace, event_text, status, _ = _wait_for_v3_background_workspace(
            background_client,
            session_id="sess_bg_v3_engines",
            repositories=v3_repositories,
            is_ready=lambda workspace, _events, _status: (
                "deep_research" in workspace["capabilities"]
                and workspace["capabilities"]["deep_research"][0]["status"]
                == "succeeded"
                    and any(
                        item["task"]["task_id"] == "task_research_v3"
                        and item["task"]["status"] == "completed"
                        for item in workspace["task_board"]["items"]
                    )
                    and any(
                        message["role"] == "assistant"
                        and message["content"] == "Research complete."
                        for message in workspace["conversation"]
                    )
                ),
        )
        assert status["running"] is True
        assert status["worker_id"] == "host-api:background-runtime"
        assert "event: signal.claimed" in event_text
        assert "event: signal.completed" in event_text
        assert model_factory.invokers["v3_harness_loop"].calls >= 2
        assert model_factory.invokers["v3_teammate_loop:researcher"].calls >= 2
        assert any(
            message["role"] == "assistant" and message["content"] == "Research complete."
            for message in research_workspace["conversation"]
        )

        execution_task = background_client.post(
            "/v3/tasks",
            json={
                "session_id": "sess_bg_v3_engines",
                "task_id": "task_execution_v3",
                "subject": "Run fpocket",
                "description": "Run fpocket against the candidate structure.",
                "kind": "execution",
                "lane_id": "lane_bg_v3_engines",
            },
        )
        assert execution_task.status_code == 200
        master_calls_before_execution = model_factory.invokers["v3_harness_loop"].calls
        execution = background_client.post(
            "/v3/sessions/sess_bg_v3_engines/messages",
            json={
                "message": "Run the execution task.",
                "task_id": "task_execution_v3",
            },
        )
        assert execution.status_code == 200
        assert execution.json()["outputs"] == []

        execution_workspace, event_text, status, resolved_approvals = (
            _wait_for_v3_background_workspace(
                background_client,
                session_id="sess_bg_v3_engines",
                repositories=v3_repositories,
                is_ready=lambda workspace, _events, _status: (
                    "execution" in workspace["capabilities"]
                    and workspace["capabilities"]["execution"][0]["status"]
                    == "succeeded"
                    and bool(workspace["artifacts"])
                    and any(
                        item["task"]["task_id"] == "task_execution_v3"
                        and item["task"]["status"] == "completed"
                        for item in workspace["task_board"]["items"]
                    )
                ),
            )
        )
        assert resolved_approvals
        assert all(
            v3_repositories.approvals.get(approval_id).status.value == "approved"
            for approval_id in resolved_approvals
        )
        assert sum(
            signal.status.value == "completed"
            and signal.claimed_by == "host-api:background-runtime"
            for signal in v3_repositories.runtime_signals.list_by_session(
                "sess_bg_v3_engines"
            )
        ) >= 3
        assert model_factory.invokers["v3_harness_loop"].calls > master_calls_before_execution
        assert model_factory.invokers["v3_teammate_loop:executor"].calls >= 3
        executor_projection = next(
            agent
            for agent in execution_workspace["delegation"]["agents"]
            if agent["agent"]["role"] == "executor"
        )
        assert executor_projection["latest_signal_reason"] is not None
        assert isinstance(executor_projection["pending_signal_count"], int)

        reporting_task = background_client.post(
            "/v3/tasks",
            json={
                "session_id": "sess_bg_v3_engines",
                "task_id": "task_report_v3",
                "subject": "Publish report",
                "description": "Publish the integrated workspace report.",
                "kind": "reporting",
                "lane_id": "lane_bg_v3_engines",
            },
        )
        assert reporting_task.status_code == 200
        reporting = background_client.post(
            "/v3/sessions/sess_bg_v3_engines/messages",
            json={
                "message": "Publish the final report.",
                "task_id": "task_report_v3",
            },
        )
        assert reporting.status_code == 200, reporting.text
        assert reporting.json()["outputs"] == []

        final_workspace, event_text, status, _ = _wait_for_v3_background_workspace(
            background_client,
            session_id="sess_bg_v3_engines",
            is_ready=lambda workspace, _events, _status: (
                bool(workspace["reports"])
                and workspace["reports"][0]["status"] == "ready"
                and any(
                    item["task"]["task_id"] == "task_report_v3"
                    and item["task"]["status"] == "completed"
                    for item in workspace["task_board"]["items"]
                )
            ),
        )
        assert status["running"] is True
        assert "event: report.generated" in event_text
        assert model_factory.invokers["v3_teammate_loop:reporter"].calls >= 3
        assert {item["task"]["kind"] for item in final_workspace["task_board"]["items"]} >= {
            "research",
            "execution",
            "reporting",
        }
        assert {"researcher", "executor", "reporter"} <= {
            item["agent"]["role"] for item in final_workspace["delegation"]["agents"]
        }


def test_v3_background_runtime_debug_exposes_model_factory_disabled_reason(
    monkeypatch,
) -> None:
    client, foundation = _build_client(monkeypatch, with_model_factory=False)
    del client
    app = create_app(
        HostApiDependencies(
            foundation=foundation,
            security_policy=_local_test_security(),
            v3_background_runtime_enabled=True,
        )
    )
    with TestClient(app) as background_client:
        status = background_client.get("/debug/v3-runtime")

    assert status.status_code == 200
    payload = status.json()
    assert payload["enabled"] is True
    assert payload["running"] is False
    assert payload["disabled_reason"] == "model_factory unavailable"


def test_v3_master_agents_and_signals_are_session_scoped() -> None:
    repositories = _build_v3_engine_repositories()
    model_factory = FakeEchoHarnessModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(project_id="proj_001", objective="A", session_id="sess_a")
    service.create_session(project_id="proj_001", objective="B", session_id="sess_b")

    service.post_message(session_id="sess_a", message="Plan A.")
    service.post_message(session_id="sess_b", message="Plan B.")

    agent_a = repositories.agents.get("sess_a", "agent:master")
    agent_b = repositories.agents.get("sess_b", "agent:master")
    assert agent_a is not None
    assert agent_b is not None
    assert agent_a.member_id != agent_b.member_id
    assert [
        signal.agent_id
        for signal in repositories.runtime_signals.list_pending_by_session("sess_a")
    ] == ["agent:master"]
    assert [
        signal.agent_id
        for signal in repositories.runtime_signals.list_pending_by_session("sess_b")
    ] == ["agent:master"]

    drained_a = service.drain_runtime(session_id="sess_a")
    assert drained_a.status == "completed"
    assert [signal.status.value for signal in repositories.runtime_signals.list_by_session("sess_a")] == ["completed"]
    assert [signal.status.value for signal in repositories.runtime_signals.list_by_session("sess_b")] == ["pending"]
    assert repositories.agents.get("sess_a", "agent:master").member_id == agent_a.member_id
    assert repositories.agents.get("sess_b", "agent:master").member_id == agent_b.member_id

    drained_b = service.drain_runtime(session_id="sess_b")
    assert drained_b.status == "completed"
    assert [signal.status.value for signal in repositories.runtime_signals.list_by_session("sess_b")] == ["completed"]
    assert [message.payload_ref for message in repositories.inbox.list_by_session("sess_a")] != [
        message.payload_ref for message in repositories.inbox.list_by_session("sess_b")
    ]


def test_v3_runtime_drain_claims_master_signal_and_runs_master_loop() -> None:
    repositories = _build_v3_engine_repositories()
    model_factory = FakeEchoHarnessModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        objective="Run the master via scheduler.",
        session_id="sess_master_claim",
    )
    posted = service.post_message(
        session_id="sess_master_claim",
        message="Start planning.",
    )
    assert posted.outputs == ()

    drained = service.drain_runtime(session_id="sess_master_claim")

    assert drained.status == "completed"
    assert drained.outputs == ("Planning started.",)
    signals = repositories.runtime_signals.list_by_session("sess_master_claim")
    assert len(signals) == 1
    assert signals[0].status.value == "completed"
    assert signals[0].claimed_by == "host-api:runtime-drain"


def test_v3_runtime_replay_extends_sanitized_trace_events_without_duplicates() -> None:
    repositories = _build_v3_engine_repositories()
    event_store = V3EventStore()
    service = V3HostApiService(
        repositories=repositories,
        event_store=event_store,
    )
    service.create_session(
        project_id="proj_001",
        objective="Replay persisted trace events.",
        session_id="sess_trace_replay",
    )
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="llmtrace_replay_001",
            session_id="sess_trace_replay",
            invocation_id=None,
            document_kind="llm_trace_step",
            payload={
                "trace_id": "llmtrace_replay_001",
                "actor_ref": "harness",
                "actor_kind": "master",
                "display_name": "OpenZyme",
                "role": "master",
                "call_index": 1,
                "created_at": "2026-04-21T00:00:02+00:00",
                "response_text": "I will inspect the task.",
                "initial_prompt": {"instructions": "private prompt"},
                "restore_context": {"memory_summary": "private memory"},
                "tool_calls": [
                    {
                        "call_id": "call_001",
                        "tool_name": "task.get",
                        "task_id": "task_001",
                        "lane_id": "lane_001",
                        "args_public": {
                            "task_id": "task_001",
                            "secret_token": "abc123",
                            "host_path": "/home/user/private/input.pdb",
                            "storage_uri": "storage://private/input.pdb",
                        },
                        "content": "private tool result",
                    }
                ],
            },
            created_at="2026-04-21T00:00:02+00:00",
            updated_at="2026-04-21T00:00:02+00:00",
        )
    )

    first = service.drain_runtime(session_id="sess_trace_replay")
    second = service.drain_runtime(session_id="sess_trace_replay")

    first_trace_events = [
        event
        for event in first.events
        if event["event_type"] == "llm.response.created"
    ]
    second_trace_events = [
        event
        for event in second.events
        if event["event_type"] == "llm.response.created"
    ]
    stored_trace_events = [
        event
        for event in event_store.list("sess_trace_replay")
        if event["event_type"] == "llm.response.created"
    ]
    assert len(first_trace_events) == 1
    assert second_trace_events == []
    assert len(stored_trace_events) == 1
    payload = first_trace_events[0]["payload"]
    assert payload["projection_schema_version"] == "v1"
    assert payload["tool_calls"][0]["args_public"]["secret_token"] == "[redacted]"
    assert payload["tool_calls"][0]["args_public"]["host_path"] == "[redacted]"
    assert payload["tool_calls"][0]["args_public"]["storage_uri"] == "[redacted]"
    payload_text = json.dumps(payload, sort_keys=True)
    assert "initial_prompt" not in payload_text
    assert "private prompt" not in payload_text
    assert "private memory" not in payload_text
    assert "private tool result" not in payload_text
    assert "/home/user/private" not in payload_text
    assert "storage://private" not in payload_text


def test_v3_resolve_unassigned_approval_enqueues_master_wakeup() -> None:
    repositories = _build_v3_engine_repositories()
    model_factory = FakeHarnessModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        objective="Resolve generic approval.",
        session_id="sess_approval_master",
    )
    repositories.approvals.save(
        ApprovalRequest(
            approval_id="appr_master",
            session_id="sess_approval_master",
            task_id=None,
            lane_id=None,
            kind="user_confirmation",
            requested_action="Confirm next step.",
            status=ApprovalRequestStatus.PENDING,
            request_ref=None,
            resolution_ref=None,
            created_at="2026-05-03T15:59:10+00:00",
        )
    )

    result = service.resolve_approval(
        "appr_master", decision="approved", actor_ref="tester"
    )

    assert result.status == "completed"
    assert result.outputs == ()
    assert model_factory.invokers == {}
    signals = repositories.runtime_signals.list_by_session("sess_approval_master")
    assert len(signals) == 1
    assert signals[0].agent_id == "agent:master"
    assert signals[0].reason.value == "approval_resolved"
    assert signals[0].source_ref == "appr_master"


def test_v3_resolve_sdk_controlled_operation_uses_continuation_not_agent_wakeup(tmp_path: Path) -> None:
    repositories = _build_v3_engine_repositories()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=FakeHarnessModelFactory(),
    )
    service.create_session(
        project_id="proj_001",
        objective="Resolve SDK controlled operation approval.",
        session_id="sess_sdk_approval",
    )
    agent = AgentMember(
        agent_id="agent:executor:sdk_approval",
        session_id="sess_sdk_approval",
        lane_id=None,
        task_id=None,
        name="Executor",
        role="executor",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-05-03T15:59:00+00:00",
        updated_at="2026-05-03T15:59:00+00:00",
        member_id="member_executor",
    )
    repositories.agents.save(agent)
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref="localhost/openzyme-pipeline-sandbox@sha256:s10",
            image_digest="sha256:s10",
        )
    )
    workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=tmp_path / "workspaces",
    ).create_or_get(session_id="sess_sdk_approval", agent_member_id="member_executor")
    run = SandboxRunRecord(
        sandbox_run_id="srun_sdk_approval",
        session_id="sess_sdk_approval",
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=("python", "src/s10.py"),
        argv_digest="sha256:argv",
        cwd="/workspace",
        env_digest="sha256:env",
        status=SandboxRunStatus.RUNNING,
        source_snapshot_artifact_id=None,
        source_tree_digest="sha256:source",
        changed_files_summary={},
        created_at="2026-05-03T15:59:01+00:00",
        updated_at="2026-05-03T15:59:01+00:00",
    )
    repositories.sandbox_runs.save(run)
    approval = ApprovalRequest(
        approval_id="appr_sdk_controlled",
        session_id="sess_sdk_approval",
        task_id=None,
        lane_id=None,
        kind="sdk_controlled_operation",
        requested_action="Approve fake SDK operation.",
        status=ApprovalRequestStatus.PENDING,
        request_ref="op_sdk_controlled",
        resolution_ref=None,
        created_at="2026-05-03T15:59:02+00:00",
    )
    repositories.approvals.save(approval)
    operation = ControlledOperation(
        operation_id="op_sdk_controlled",
        session_id="sess_sdk_approval",
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id=run.sandbox_run_id,
        logical_operation_key="fake.controlled",
        operation_digest="sha256:operation",
        params_digest="sha256:params",
        backend_category="provider_http",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        approval_id=approval.approval_id,
        approval_state=ApprovalRequestStatus.PENDING.value,
        route_reason="s10_generic_backend_category",
        expected_outputs_summary={},
        resource_estimate={},
        created_at="2026-05-03T15:59:03+00:00",
        updated_at="2026-05-03T15:59:03+00:00",
    )
    repositories.controlled_operations.save(operation)
    continuation = ContinuationState(
        continuation_id="srun_sdk_approval:op_sdk_controlled",
        session_id="sess_sdk_approval",
        operation_id=operation.operation_id,
        sandbox_run_id=run.sandbox_run_id,
        approval_id=approval.approval_id,
        status=ContinuationStateStatus.WAITING_APPROVAL,
        created_at="2026-05-03T15:59:04+00:00",
        updated_at="2026-05-03T15:59:04+00:00",
    )
    repositories.continuation_states.save(continuation)

    pending_projection = service.workspace("sess_sdk_approval")["pending_approvals"][0]
    assert pending_projection["approval_id"] == approval.approval_id
    assert pending_projection["operation"]["operation_id"] == operation.operation_id
    assert pending_projection["operation"]["logical_operation_key"] == "fake.controlled"
    assert (
        pending_projection["operation"]["operation_digest"]
        == operation.operation_digest
    )
    assert pending_projection["sandbox_run"]["sandbox_run_id"] == run.sandbox_run_id
    pending_evidence_operation = service.workspace("sess_sdk_approval")[
        "scientific_evidence"
    ]["operations"][0]
    assert pending_evidence_operation["operation_id"] == operation.operation_id
    assert pending_evidence_operation["operation_digest"] == operation.operation_digest
    assert pending_evidence_operation["approval_id"] == approval.approval_id
    assert pending_evidence_operation["approval_state"] == "pending"

    result = service.resolve_approval(
        approval.approval_id,
        decision="approved",
        actor_ref="tester",
    )

    assert result.status == "completed"
    assert repositories.runtime_signals.list_by_session("sess_sdk_approval") == []
    resolved = repositories.approvals.get(approval.approval_id)
    assert resolved is not None
    assert resolved.status is ApprovalRequestStatus.APPROVED
    updated_operation = repositories.controlled_operations.get(operation.operation_id)
    assert updated_operation is not None
    assert updated_operation.approval_state == "approved"
    assert updated_operation.status is ControlledOperationStatus.WAITING_APPROVAL
    updated_continuation = repositories.continuation_states.get(continuation.continuation_id)
    assert updated_continuation is not None
    assert updated_continuation.status is ContinuationStateStatus.APPROVED
    sdk_projection = result.workspace["capabilities"]["sdk_supervisor"][0]
    assert sdk_projection["operation_id"] == operation.operation_id
    assert sdk_projection["operation_digest"] == operation.operation_digest
    assert sdk_projection["approval_state"] == "approved"
    assert sdk_projection["backend_category"] == "provider_http"
    assert any(
        item["event_type"] == "sdk_controlled_operation.updated"
        and item["payload"]["operation_id"] == operation.operation_id
        for item in result.workspace["activity_feed"]
    )
    assert any(
        event["event_type"] == "sdk_controlled_operation.approval_resolved"
        and event["payload"]["operation_id"] == operation.operation_id
        and event["payload"]["operation_digest"] == operation.operation_digest
        for event in result.events
    )
    resumed_evidence_operation = result.workspace["scientific_evidence"]["operations"][
        0
    ]
    assert resumed_evidence_operation["operation_id"] == operation.operation_id
    assert resumed_evidence_operation["operation_digest"] == operation.operation_digest
    assert resumed_evidence_operation["approval_id"] == approval.approval_id
    assert resumed_evidence_operation["approval_state"] == "approved"

    duplicate = service.resolve_approval(
        approval.approval_id,
        decision="approved",
        actor_ref="tester",
    )
    assert duplicate.status == "completed"
    assert repositories.runtime_signals.list_by_session("sess_sdk_approval") == []
    duplicate_continuation = repositories.continuation_states.get(
        continuation.continuation_id
    )
    assert duplicate_continuation is not None
    assert duplicate_continuation.status is ContinuationStateStatus.APPROVED

    reject_approval = replace(
        approval,
        approval_id="appr_sdk_rejected",
        request_ref="op_sdk_rejected",
        status=ApprovalRequestStatus.PENDING,
        resolved_at=None,
        created_at="2026-05-03T16:00:02+00:00",
    )
    repositories.approvals.save(reject_approval)
    reject_operation = replace(
        operation,
        operation_id="op_sdk_rejected",
        approval_id=reject_approval.approval_id,
        approval_state=ApprovalRequestStatus.PENDING.value,
        status=ControlledOperationStatus.WAITING_APPROVAL,
        error_code=None,
        error_summary=None,
        created_at="2026-05-03T16:00:03+00:00",
        updated_at="2026-05-03T16:00:03+00:00",
    )
    repositories.controlled_operations.save(reject_operation)
    reject_continuation = replace(
        continuation,
        continuation_id="srun_sdk_approval:op_sdk_rejected",
        operation_id=reject_operation.operation_id,
        approval_id=reject_approval.approval_id,
        status=ContinuationStateStatus.WAITING_APPROVAL,
        created_at="2026-05-03T16:00:04+00:00",
        updated_at="2026-05-03T16:00:04+00:00",
    )
    repositories.continuation_states.save(reject_continuation)

    rejected = service.resolve_approval(
        reject_approval.approval_id,
        decision="rejected",
        actor_ref="tester",
    )
    duplicate_reject = service.resolve_approval(
        reject_approval.approval_id,
        decision="rejected",
        actor_ref="tester",
    )
    assert rejected.status == "completed"
    assert duplicate_reject.status == "completed"
    updated_reject_operation = repositories.controlled_operations.get(
        reject_operation.operation_id
    )
    assert updated_reject_operation is not None
    assert updated_reject_operation.status is ControlledOperationStatus.FAILED
    assert updated_reject_operation.error_code == "approval_rejected"
    assert repositories.runtime_signals.list_by_session("sess_sdk_approval") == []
    try:
        service.resolve_approval(
            reject_approval.approval_id,
            decision="approved",
            actor_ref="tester",
        )
    except ValueError as exc:
        assert "approval_state_conflict" in str(exc)
    else:
        raise AssertionError("expected approval_state_conflict")


def test_v3_resolve_durable_controlled_operation_advances_only_canonical_execution(
    tmp_path: Path,
) -> None:
    repositories = _build_v3_engine_repositories()
    durable_notifier = RuntimeSignalNotifier()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=FakeHarnessModelFactory(),
        durable_work_notifier=durable_notifier,
    )
    service.create_session(
        project_id="proj_001",
        objective="Resolve durable SDK controlled operation approval.",
        session_id="sess_durable_approval",
    )
    agent = AgentMember(
        agent_id="agent:executor:durable_approval",
        session_id="sess_durable_approval",
        lane_id=None,
        task_id=None,
        name="Executor",
        role="executor",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-07-21T00:00:00+00:00",
        updated_at="2026-07-21T00:00:00+00:00",
        member_id="member_durable_executor",
    )
    repositories.agents.save(agent)
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref="localhost/openzyme-pipeline-sandbox@sha256:durable",
            image_digest="sha256:durable",
        )
    )
    workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=tmp_path / "workspaces",
    ).create_or_get(
        session_id="sess_durable_approval",
        agent_member_id=agent.member_id,
    )
    run = SandboxRunRecord(
        sandbox_run_id="srun_durable_approval",
        session_id="sess_durable_approval",
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=("python", "src/durable.py"),
        argv_digest="sha256:argv",
        cwd="/workspace",
        env_digest="sha256:env",
        status=SandboxRunStatus.RUNNING,
        source_snapshot_artifact_id=None,
        source_tree_digest="sha256:source",
        changed_files_summary={},
        created_at="2026-07-21T00:00:01+00:00",
        updated_at="2026-07-21T00:00:01+00:00",
    )
    repositories.sandbox_runs.save(run)
    approval = ApprovalRequest(
        approval_id="appr_durable_controlled",
        session_id="sess_durable_approval",
        task_id=None,
        lane_id=None,
        kind="sdk_controlled_operation",
        requested_action="Approve durable fixture operation.",
        status=ApprovalRequestStatus.PENDING,
        request_ref="op_durable_controlled",
        resolution_ref=None,
        created_at="2026-07-21T00:00:02+00:00",
    )
    operation = ControlledOperation(
        operation_id="op_durable_controlled",
        session_id="sess_durable_approval",
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id=run.sandbox_run_id,
        logical_operation_key="fixture.run",
        operation_digest="sha256:durable-operation",
        params_digest="sha256:durable-params",
        backend_category="fixture",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        approval_id=approval.approval_id,
        approval_state=ApprovalRequestStatus.PENDING.value,
        route_policy_id="fixture_v1",
        selected_backend="fixture",
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        expected_outputs_summary={},
        resource_estimate={},
        planned_fetch_intent={},
        approval_requirement={},
        adapter_approval_envelope={},
        adapter_result_envelope={},
        result_summary={},
        created_at="2026-07-21T00:00:03+00:00",
        updated_at="2026-07-21T00:00:03+00:00",
    )
    execution = ControlledOperationExecution(
        execution_id="exec_durable_controlled",
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        operation_digest=operation.operation_digest,
        approval_digest=controlled_operation_approval_digest(approval),
        route_policy_id="fixture_v1",
        selected_backend="fixture",
        adapter_policy_id="fixture_adapter_v1",
        input_identity_digest="sha256:durable-inputs",
        expected_output_contract_digest="sha256:durable-outputs",
        runtime_identity_digest="sha256:durable-runtime",
        lifecycle_state=ControlledOperationExecutionLifecycle.AWAITING_APPROVAL,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        dispatch_generation=0,
        state_version=1,
        fencing_token=0,
        approval_id=approval.approval_id,
        created_at="2026-07-21T00:00:03+00:00",
        updated_at="2026-07-21T00:00:03+00:00",
    )
    request_envelope = {
        "schema_version": "durable_route_request@1",
        "adapter_params": {"value": "fixture"},
    }
    encoded_request = json.dumps(
        request_envelope,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    dispatch_request = ControlledOperationDispatchRequest(
        request_id="dispatch_durable_controlled",
        execution_id=execution.execution_id,
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        request_digest="sha256:" + hashlib.sha256(encoded_request).hexdigest(),
        request_envelope=request_envelope,
        request_size_bytes=len(encoded_request),
        created_at="2026-07-21T00:00:03+00:00",
    )
    continuation = ContinuationState(
        continuation_id="continuation_durable_controlled",
        session_id=operation.session_id,
        operation_id=operation.operation_id,
        sandbox_run_id=run.sandbox_run_id,
        approval_id=approval.approval_id,
        status=ContinuationStateStatus.WAITING_APPROVAL,
        created_at="2026-07-21T00:00:03+00:00",
        updated_at="2026-07-21T00:00:03+00:00",
    )
    event = ControlledOperationExecutionEvent(
        event_id="event_durable_admission",
        execution_id=execution.execution_id,
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        state_version=1,
        dispatch_generation=0,
        phase=ControlledOperationExecutionPhase.ADMISSION,
        lifecycle_state=ControlledOperationExecutionLifecycle.AWAITING_APPROVAL,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        fencing_token=0,
        created_at="2026-07-21T00:00:03+00:00",
    )
    DurableControlledOperationAdmissionService(repositories).admit(
        DurableControlledOperationAdmission(
            operation=operation,
            approval=approval,
            execution=execution,
            dispatch_request=dispatch_request,
            continuation=continuation,
            event=event,
        )
    )

    result = service.resolve_approval(
        approval.approval_id,
        decision="approved",
        actor_ref="tester",
    )

    assert result.status == "completed"
    resolved_execution = repositories.controlled_operation_executions.get(
        execution.execution_id
    )
    assert resolved_execution is not None
    assert resolved_execution.lifecycle_state is ControlledOperationExecutionLifecycle.READY
    assert resolved_execution.state_version == 2
    resolved_operation = repositories.controlled_operations.get(
        operation.operation_id
    )
    assert resolved_operation is not None
    assert resolved_operation.status is ControlledOperationStatus.RUNNING
    assert resolved_operation.approval_state == "approved"
    resolved_continuation = repositories.continuation_states.get(
        continuation.continuation_id
    )
    assert resolved_continuation is not None
    assert resolved_continuation.status is ContinuationStateStatus.APPROVED
    assert durable_notifier.notify_count == 1

    recovery_events = service.recover_abandoned_sdk_continuations()
    assert recovery_events == []
    assert repositories.continuation_states.get(
        continuation.continuation_id
    ) == resolved_continuation
    assert repositories.controlled_operation_executions.get(
        execution.execution_id
    ) == resolved_execution

    rejected_approval = replace(
        approval,
        approval_id="appr_durable_rejected",
        request_ref="op_durable_rejected",
    )
    rejected_operation = replace(
        operation,
        operation_id="op_durable_rejected",
        approval_id=rejected_approval.approval_id,
    )
    rejected_execution = replace(
        execution,
        execution_id="exec_durable_rejected",
        operation_id=rejected_operation.operation_id,
        approval_id=rejected_approval.approval_id,
        approval_digest=controlled_operation_approval_digest(rejected_approval),
    )
    rejected_request = replace(
        dispatch_request,
        request_id="dispatch_durable_rejected",
        execution_id=rejected_execution.execution_id,
        operation_id=rejected_operation.operation_id,
    )
    rejected_continuation = replace(
        continuation,
        continuation_id="continuation_durable_rejected",
        operation_id=rejected_operation.operation_id,
        approval_id=rejected_approval.approval_id,
    )
    rejected_event = replace(
        event,
        event_id="event_durable_rejected",
        execution_id=rejected_execution.execution_id,
        operation_id=rejected_operation.operation_id,
    )
    DurableControlledOperationAdmissionService(repositories).admit(
        DurableControlledOperationAdmission(
            operation=rejected_operation,
            approval=rejected_approval,
            execution=rejected_execution,
            dispatch_request=rejected_request,
            continuation=rejected_continuation,
            event=rejected_event,
        )
    )

    rejected_result = service.resolve_approval(
        rejected_approval.approval_id,
        decision="rejected",
        actor_ref="tester",
    )

    assert rejected_result.status == "completed"
    rejected_canonical = repositories.controlled_operation_executions.get(
        rejected_execution.execution_id
    )
    assert rejected_canonical is not None
    assert rejected_canonical.lifecycle_state is (
        ControlledOperationExecutionLifecycle.TERMINAL
    )
    assert rejected_canonical.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert rejected_canonical.terminal_outcome is (
        ControlledOperationExecutionTerminalOutcome.CANCELLED
    )
    assert rejected_canonical.result_handle_ref is not None
    rejected_handle = repositories.controlled_operation_results.get_by_execution_id(
        rejected_execution.execution_id
    )
    assert rejected_handle is not None
    assert rejected_handle.result_handle_id == rejected_canonical.result_handle_ref
    assert rejected_handle.bounded_result_envelope["error_code"] == (
        "approval_rejected"
    )
    assert durable_notifier.notify_count == 1

    lost_approval = replace(
        approval,
        approval_id="appr_durable_process_lost",
        request_ref="op_durable_process_lost",
    )
    lost_operation = replace(
        operation,
        operation_id="op_durable_process_lost",
        approval_id=lost_approval.approval_id,
    )
    lost_execution = replace(
        execution,
        execution_id="exec_durable_process_lost",
        operation_id=lost_operation.operation_id,
        approval_id=lost_approval.approval_id,
        approval_digest=controlled_operation_approval_digest(lost_approval),
    )
    lost_request = replace(
        dispatch_request,
        request_id="dispatch_durable_process_lost",
        execution_id=lost_execution.execution_id,
        operation_id=lost_operation.operation_id,
    )
    lost_continuation = replace(
        continuation,
        continuation_id="continuation_durable_process_lost",
        operation_id=lost_operation.operation_id,
        approval_id=lost_approval.approval_id,
    )
    lost_event = replace(
        event,
        event_id="event_durable_process_lost",
        execution_id=lost_execution.execution_id,
        operation_id=lost_operation.operation_id,
    )
    DurableControlledOperationAdmissionService(repositories).admit(
        DurableControlledOperationAdmission(
            operation=lost_operation,
            approval=lost_approval,
            execution=lost_execution,
            dispatch_request=lost_request,
            continuation=lost_continuation,
            event=lost_event,
        )
    )
    repositories.continuation_deliveries.mark_recovery_failed(
        lost_continuation.continuation_id,
        expected_state_version=lost_continuation.state_version,
        completed_at="2026-07-21T00:01:00+00:00",
        error_code="attached_process_missing_after_restart",
        error_message="The exact attached process did not survive restart.",
    )

    with pytest.raises(ValueError, match="continuation_recovery_failed"):
        service.resolve_approval(
            lost_approval.approval_id,
            decision="approved",
            actor_ref="tester",
        )

    unresolved_lost_approval = repositories.approvals.get(lost_approval.approval_id)
    unresolved_lost_execution = repositories.controlled_operation_executions.get(
        lost_execution.execution_id
    )
    persisted_lost_continuation = repositories.continuation_states.get(
        lost_continuation.continuation_id
    )
    assert unresolved_lost_approval is not None
    assert unresolved_lost_approval.status is ApprovalRequestStatus.PENDING
    assert unresolved_lost_execution is not None
    assert unresolved_lost_execution.lifecycle_state is (
        ControlledOperationExecutionLifecycle.AWAITING_APPROVAL
    )
    assert persisted_lost_continuation is not None
    assert persisted_lost_continuation.delivery_state is (
        ContinuationDeliveryState.RECOVERY_FAILED
    )
    assert durable_notifier.notify_count == 1


def test_v3_recover_abandoned_sdk_continuation_fails_closed(tmp_path: Path) -> None:
    repositories = _build_v3_engine_repositories()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        model_factory=FakeHarnessModelFactory(),
    )
    service.create_session(
        project_id="proj_001",
        objective="Recover abandoned SDK continuation.",
        session_id="sess_sdk_recovery",
    )
    agent = AgentMember(
        agent_id="agent:executor:sdk_recovery",
        session_id="sess_sdk_recovery",
        lane_id=None,
        task_id=None,
        name="Executor",
        role="executor",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-05-03T15:59:00+00:00",
        updated_at="2026-05-03T15:59:00+00:00",
        member_id="member_executor_recovery",
    )
    repositories.agents.save(agent)
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref="localhost/openzyme-pipeline-sandbox@sha256:s10",
            image_digest="sha256:s10",
        )
    )
    workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=tmp_path / "workspaces",
    ).create_or_get(
        session_id="sess_sdk_recovery",
        agent_member_id="member_executor_recovery",
    )
    run = SandboxRunRecord(
        sandbox_run_id="srun_sdk_recovery",
        session_id="sess_sdk_recovery",
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=("python", "src/s10.py"),
        argv_digest="sha256:argv",
        cwd="/workspace",
        env_digest="sha256:env",
        status=SandboxRunStatus.RUNNING,
        source_snapshot_artifact_id=None,
        source_tree_digest="sha256:source",
        changed_files_summary={},
        created_at="2026-05-03T16:10:01+00:00",
        updated_at="2026-05-03T16:10:01+00:00",
    )
    repositories.sandbox_runs.save(run)
    approval = ApprovalRequest(
        approval_id="appr_sdk_recovery",
        session_id="sess_sdk_recovery",
        task_id=None,
        lane_id=None,
        kind="sdk_controlled_operation",
        requested_action="Approve fake SDK operation.",
        status=ApprovalRequestStatus.APPROVED,
        request_ref="op_sdk_recovery",
        resolution_ref=None,
        created_at="2026-05-03T16:10:02+00:00",
        resolved_at="2026-05-03T16:10:03+00:00",
    )
    repositories.approvals.save(approval)
    operation = ControlledOperation(
        operation_id="op_sdk_recovery",
        session_id="sess_sdk_recovery",
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id=run.sandbox_run_id,
        logical_operation_key="fake.recovery",
        operation_digest="sha256:operation",
        params_digest="sha256:params",
        backend_category="provider_http",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        approval_id=approval.approval_id,
        approval_state=ApprovalRequestStatus.APPROVED.value,
        route_reason="s10_generic_backend_category",
        expected_outputs_summary={},
        resource_estimate={},
        created_at="2026-05-03T16:10:04+00:00",
        updated_at="2026-05-03T16:10:04+00:00",
    )
    repositories.controlled_operations.save(operation)
    continuation = ContinuationState(
        continuation_id="srun_sdk_recovery:op_sdk_recovery",
        session_id="sess_sdk_recovery",
        operation_id=operation.operation_id,
        sandbox_run_id=run.sandbox_run_id,
        approval_id=approval.approval_id,
        status=ContinuationStateStatus.APPROVED,
        created_at="2026-05-03T16:10:05+00:00",
        updated_at="2026-05-03T16:10:05+00:00",
    )
    repositories.continuation_states.save(continuation)

    events = service.recover_abandoned_sdk_continuations(actor_ref="startup")

    recovered_operation = repositories.controlled_operations.get(operation.operation_id)
    recovered_continuation = repositories.continuation_states.get(
        continuation.continuation_id
    )
    recovered_run = repositories.sandbox_runs.get(run.sandbox_run_id)
    assert recovered_operation is not None
    assert recovered_operation.status is ControlledOperationStatus.RECOVERY_FAILED
    assert recovered_operation.error_code == "operation_recovery_failed"
    assert recovered_continuation is not None
    assert recovered_continuation.status is ContinuationStateStatus.RECOVERY_FAILED
    assert recovered_continuation.error_code == "operation_recovery_failed"
    assert recovered_run is not None
    assert recovered_run.status is SandboxRunStatus.FAILED
    assert recovered_run.error_code == "operation_recovery_failed"
    assert repositories.approvals.get(approval.approval_id) == approval
    assert repositories.runtime_signals.list_by_session("sess_sdk_recovery") == []
    assert any(
        event["event_type"] == "sdk_controlled_operation.recovery_failed"
        for event in events
    )


def test_hpc_operation_failed_after_approval_returns_to_executor_for_diagnostic() -> (
    None
):
    repositories = _build_v3_engine_repositories()
    repositories.sessions.save(
        Session.create(
            "sess_hpc_diag",
            "proj_001",
            "HPC diagnostic",
            "Diagnose approved execution failure.",
        )
    )
    repositories.tasks.seed_fixture(
        Task.create(
            "task_hpc_diag",
            "sess_hpc_diag",
            "Run fpocket",
            "Run fpocket and report failures.",
            kind="execution",
            status=TaskStatus.BLOCKED,
            assigned_ref="agent:executor:hpc_diag",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:executor:hpc_diag",
            session_id="sess_hpc_diag",
            lane_id=None,
            task_id="task_hpc_diag",
            name="executor",
            role="executor",
            status=AgentMemberStatus.BLOCKED,
            parent_agent_id=None,
            created_at="2026-05-03T15:59:00+00:00",
            updated_at="2026-05-03T15:59:00+00:00",
            runtime_state="blocked",
            current_correlation_id="corr_hpc_diag",
        )
    )
    repositories.approvals.save(
        ApprovalRequest(
            approval_id="appr_hpc_diag",
            session_id="sess_hpc_diag",
            task_id="task_hpc_diag",
            lane_id=None,
            kind="execution_pipeline_plan",
            requested_action="Approve fpocket.",
            status=ApprovalRequestStatus.PENDING,
            request_ref="artifact://approvals/appr_hpc_diag.json",
            resolution_ref=None,
            created_at="2026-05-03T15:59:10+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_hpc_diag",
            session_id="sess_hpc_diag",
            task_id="task_hpc_diag",
            lane_id=None,
            engine_name="execution",
            status=EngineInvocationStatus.WAITING_APPROVAL,
            input_ref="eng_in_hpc_diag",
            output_ref=None,
            approval_id="appr_hpc_diag",
            idempotency_key="hpc_diag",
            started_at="2026-05-03T15:59:10+00:00",
        )
    )
    registry = EngineRegistry()
    registry.register(FailedHpcExecutionEngine(repositories))
    model_factory = DiagnosticExecutorModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(),
        engine_registry=registry,
        model_factory=model_factory,
        bio_research_service=None,
        research_adapter=None,
    )

    result = service.resolve_approval(
        "appr_hpc_diag", decision="approved", actor_ref="tester"
    )

    assert result.status == "completed"
    assert result.outputs == ()
    assert model_factory.invoker.calls == 0
    assert model_factory.master_calls == 0
    assert repositories.runtime_signals.list_pending_by_session("sess_hpc_diag")
    task = repositories.tasks.get("task_hpc_diag")
    assert task is not None
    assert task.status is TaskStatus.BLOCKED

    drained = service.drain_runtime(session_id="sess_hpc_diag")

    assert drained.status == "completed"
    assert drained.core_receipt.scheduler_status == "completed"
    assert drained.core_receipt.processed_signal_count == 2
    assert model_factory.invoker.calls == 1
    assert model_factory.master_calls == 1
    assert drained.outputs == (
        "The approved fpocket task failed at the HPC runner boundary. "
        "The execution task is marked failed with failure_ref engine:inv_hpc_diag.",
    )
    assert "Execution failed in the approved pipeline" not in " ".join(drained.outputs)
    task = repositories.tasks.get("task_hpc_diag")
    assert task is not None
    assert task.status is TaskStatus.FAILED
    assert task.failure_ref == "engine:inv_hpc_diag"
    assert task.failure_summary is not None
    assert "INPUT_OR_ENTRYPOINT_MISSING" in task.failure_summary
    assert {
        signal.status.value
        for signal in repositories.runtime_signals.list_by_session(
            "sess_hpc_diag"
        )
    } == {"completed"}
    assistant_messages = [
        message
        for message in repositories.inbox.list_by_session("sess_hpc_diag")
        if message.message_type == "assistant_message" and message.recipient == "user"
    ]
    assert len(assistant_messages) == 1


def _seed_v3_execution_artifact(
    repositories: CoreRepositories,
    session_id: str,
    *,
    tmp_path: Path,
) -> None:
    lines = []
    serial = 1
    for residue_index in range(1, 11):
        for atom_index, atom_name in enumerate(("N", "CA", "C", "O", "CB")):
            lines.append(
                f"ATOM  {serial:5d} {atom_name:<4} ALA A{residue_index:4d}    "
                f"{float(residue_index):8.3f}{float(atom_index):8.3f}{0.0:8.3f}  1.00 20.00           C"
            )
            serial += 1
    content = "\n".join(lines) + "\nEND\n"
    structure_path = tmp_path / f"{session_id}-v3-input-structure.pdb"
    structure_path.write_text(content, encoding="utf-8")
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_v3_structure",
            session_id=session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.STRUCTURE,
            storage_uri=str(structure_path),
            relative_path="v3_input_structure.pdb",
            title="v3_input_structure.pdb",
            description=None,
            metadata={
                "source": "test_fixture",
                "format": "pdb",
                "content_digest": f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
            },
            created_at="2026-04-20T12:00:03+00:00",
        )
    )


def _build_v3_echo_llm_client(monkeypatch) -> tuple[TestClient, RuntimeFoundation]:
    client, foundation = _build_client(monkeypatch)
    return (
        TestClient(
            create_app(
                HostApiDependencies(
                    foundation=replace(
                        foundation, model_factory=FakeEchoHarnessModelFactory()
                    ),
                    v3_background_runtime_enabled=False,
                )
            )
        ),
        foundation,
    )


def test_v3_session_message_events_task_and_lane(monkeypatch, request) -> None:
    client, _ = _build_v3_echo_llm_client(monkeypatch)
    _start_runtime_command_client(client, request)

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_001",
            "project_id": "proj_001",
            "objective": "Plan an enzyme design run",
        },
    )

    assert created.status_code == 200
    workspace = created.json()["workspace"]
    assert workspace["session"]["session_id"] == "sess_v3_001"
    assert workspace["task_board"]["items"] == []

    lane = client.post(
        "/v3/lanes",
        json={
            "session_id": "sess_v3_001",
            "lane_id": "lane_v3_001",
            "name": "analysis",
            "cwd": "/tmp/openzyme-v3-analysis",
        },
    )
    assert lane.status_code == 200
    assert lane.json()["lane"]["status"] == "idle"

    task = client.post(
        "/v3/tasks",
        json={
            "session_id": "sess_v3_001",
            "task_id": "task_v3_001",
            "subject": "Extract design goals",
            "description": "Read the paper and extract enzyme design objectives.",
            "lane_id": "lane_v3_001",
            "priority": "high",
        },
    )
    assert task.status_code == 200
    assert task.json()["task"]["lane_id"] == "lane_v3_001"

    message = client.post(
        "/v3/sessions/sess_v3_001/messages",
        json={
            "message": "Start by planning the literature extraction.",
            "task_id": "task_v3_001",
        },
    )
    assert message.status_code == 200
    payload = message.json()
    assert payload["outputs"] == []
    assert {event["event_type"] for event in payload["events"]} >= {
        "conversation.user_message",
        "signal.queued",
    }

    drained = _admit_and_observe_runtime_command(
        client,
        session_id="sess_v3_001",
    )
    assert drained.status_code == 202
    payload = drained.json()
    assert payload["outputs"] == ["Planning started."]
    assert {event["event_type"] for event in payload["events"]} >= {
        "llm.response.created",
        "message.sent",
    }
    assert payload["workspace"]["inbox"]
    assert (
        payload["workspace"]["agent_traces"]["harness"][0]["response_text"]
        == "Planning started."
    )

    events = client.get("/v3/sessions/sess_v3_001/events?replay=1")
    assert events.status_code == 200
    assert "event: conversation.user_message" in events.text
    assert "event: llm.response.created" in events.text

    updated = client.patch("/v3/tasks/task_v3_001", json={"status": "in_progress"})
    assert updated.status_code == 200
    assert updated.json()["task"]["status"] == "in_progress"


def test_v3_pressure_user_message_triggers_budget_compaction_via_message_loop(
    monkeypatch,
    request,
) -> None:
    _clear_context_budget_env(monkeypatch)
    model_factory = PressureHarnessModelFactory(
        [{"content": "pressure message handled", "tool_calls": []}],
        context_window_tokens=105_000,
    )
    client, repositories, model_factory = _build_v3_pressure_client(
        monkeypatch, model_factory
    )
    _start_runtime_command_client(client, request)

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_pressure_compact",
            "project_id": "proj_001",
            "objective": "Pressure test prompt compaction",
        },
    )
    assert created.status_code == 200

    message = client.post(
        "/v3/sessions/sess_pressure_compact/messages",
        json={"message": "正常用户消息：" + ("x" * 320_000)},
    )
    assert message.status_code == 200
    assert message.json()["outputs"] == []

    drained = _admit_and_observe_runtime_command(
        client,
        session_id="sess_pressure_compact",
        request={"max_steps_per_agent": 1},
    )
    assert drained.status_code == 202
    payload = drained.json()
    event_types = [event["event_type"] for event in payload["events"]]

    assert payload["status"] == "completed"
    assert payload["outputs"] == ["pressure message handled"]
    assert len(model_factory.invokers["v3_harness_loop"].calls) == 1
    assert "llm.context_budget.warning" in event_types
    assert "llm.context_budget.after_compaction" in event_types
    assert "llm.context_budget.exceeded" not in event_types
    assert event_types.index("llm.context_budget.after_compaction") < event_types.index(
        "llm.response.created"
    )
    prompt_compactions = [
        memory
        for memory in repositories.memory.list_by_session("sess_pressure_compact")
        if memory.kind.value == "compaction"
        and memory.source_range == "auto:prompt_budget"
    ]
    assert prompt_compactions
    assert "auto_compact before model call" in prompt_compactions[-1].summary


def test_v3_prompt_budget_compaction_cuts_off_prior_conversation_for_later_drains(
    monkeypatch,
    request,
) -> None:
    _clear_context_budget_env(monkeypatch)
    large_marker = "large-round-one-marker"
    model_factory = PressureHarnessModelFactory(
        [
            {"content": f"round {round_index} handled", "tool_calls": []}
            for round_index in range(1, 6)
        ],
        context_window_tokens=105_000,
    )
    client, repositories, model_factory = _build_v3_pressure_client(
        monkeypatch, model_factory
    )
    _start_runtime_command_client(client, request)
    session_id = "sess_pressure_multiround"

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": session_id,
            "project_id": "proj_001",
            "objective": "Pressure test prompt compaction reuse",
        },
    )
    assert created.status_code == 200

    message = client.post(
        f"/v3/sessions/{session_id}/messages",
        json={"message": large_marker + ":" + ("x" * 320_000)},
    )
    assert message.status_code == 200
    drained = _admit_and_observe_runtime_command(
        client,
        session_id=session_id,
        request={"max_steps_per_agent": 1},
    )
    assert drained.status_code == 202
    first_payload = drained.json()
    first_event_types = [event["event_type"] for event in first_payload["events"]]
    first_warning = [
        event["payload"]
        for event in first_payload["events"]
        if event["event_type"] == "llm.context_budget.warning"
    ][-1]
    first_after_compaction = [
        event["payload"]
        for event in first_payload["events"]
        if event["event_type"] == "llm.context_budget.after_compaction"
    ][-1]

    assert first_payload["outputs"] == ["round 1 handled"]
    assert "llm.response.created" in first_event_types
    assert first_warning["action"] == "emergency"
    assert first_warning["ratio"] >= 0.90
    assert first_after_compaction["action"] != "emergency"
    assert first_after_compaction["ratio"] < first_warning["ratio"]

    invoker = model_factory.invokers["v3_harness_loop"]
    for round_index in range(2, 6):
        message = client.post(
            f"/v3/sessions/{session_id}/messages",
            json={"message": f"small round {round_index}"},
        )
        assert message.status_code == 200
        drained = _admit_and_observe_runtime_command(
            client,
            session_id=session_id,
            request={"max_steps_per_agent": 1},
        )
        assert drained.status_code == 202
        payload = drained.json()
        event_types = [event["event_type"] for event in payload["events"]]

        assert payload["outputs"] == [f"round {round_index} handled"]
        assert "llm.response.created" in event_types
        assert "llm.context_budget.after_compaction" not in event_types
        assert "llm.context_budget.exceeded" not in event_types
        provider_prompt = "\n".join(
            _message_content(message)
            for message in invoker.calls[-1]["messages"]
        )
        assert large_marker not in provider_prompt
        assert f"small round {round_index}" in provider_prompt
        prompt_compactions = [
            memory
            for memory in repositories.memory.list_by_session(session_id)
            if memory.kind.value == "compaction"
            and memory.source_range == "auto:prompt_budget"
        ]
        assert len(prompt_compactions) == 1

    assert len(invoker.calls) == 5


def test_v3_glm51_default_window_budget_boundaries_via_message_loop(
    monkeypatch,
    request,
) -> None:
    _clear_context_budget_env(monkeypatch)
    cases = [
        ("below_warn", 250_000, "ok"),
        ("warn", 360_000, "warn"),
        ("auto", 400_000, "auto_compact"),
    ]

    for suffix, message_size, expected_action in cases:
        model_factory = PressureHarnessModelFactory(
            [{"content": f"{suffix} handled", "tool_calls": []}],
            model="glm-5.1",
            context_window_tokens=None,
            default_output_tokens=None,
        )
        client, repositories, model_factory = _build_v3_pressure_client(
            monkeypatch, model_factory
        )
        _start_runtime_command_client(client, request)
        session_id = f"sess_glm51_budget_{suffix}"

        created = client.post(
            "/v3/sessions",
            json={
                "session_id": session_id,
                "project_id": "proj_001",
                "objective": f"Pressure test GLM-5.1 default boundary {suffix}",
            },
        )
        assert created.status_code == 200

        message = client.post(
            f"/v3/sessions/{session_id}/messages",
            json={"message": "正常窗口边界测试：" + ("x" * message_size)},
        )
        assert message.status_code == 200

        drained = _admit_and_observe_runtime_command(
            client,
            session_id=session_id,
            request={"max_steps_per_agent": 1},
        )
        assert drained.status_code == 202
        payload = drained.json()
        event_types = [event["event_type"] for event in payload["events"]]
        budget_payloads = [
            event["payload"]
            for event in payload["events"]
            if event["event_type"] == "llm.context_budget.warning"
        ]

        assert payload["status"] == "completed"
        assert payload["outputs"] == [f"{suffix} handled"]
        assert "llm.context_budget.exceeded" not in event_types
        assert len(model_factory.invokers["v3_harness_loop"].calls) == 1
        if expected_action == "ok":
            assert budget_payloads == []
            assert "llm.context_budget.after_compaction" not in event_types
            assert not [
                memory
                for memory in repositories.memory.list_by_session(session_id)
                if memory.kind.value == "compaction"
                and memory.source_range == "auto:prompt_budget"
            ]
            continue

        assert budget_payloads
        assert budget_payloads[-1]["model"] == "glm-5.1"
        assert budget_payloads[-1]["context_window_tokens"] == 200_000
        assert budget_payloads[-1]["reserved_output_tokens"] == 65_536
        assert budget_payloads[-1]["action"] == expected_action
        if expected_action == "warn":
            assert 0.80 <= budget_payloads[-1]["ratio"] < 0.85
            assert "llm.context_budget.after_compaction" not in event_types
        else:
            assert 0.85 <= budget_payloads[-1]["ratio"] < 0.90
            assert "llm.context_budget.after_compaction" in event_types
            assert event_types.index(
                "llm.context_budget.after_compaction"
            ) < event_types.index("llm.response.created")
            prompt_compactions = [
                memory
                for memory in repositories.memory.list_by_session(session_id)
                if memory.kind.value == "compaction"
                and memory.source_range == "auto:prompt_budget"
            ]
            assert prompt_compactions
            assert "auto_compact before model call" in prompt_compactions[-1].summary


def test_v3_pressure_large_tool_result_artifactized_via_message_loop(
    monkeypatch,
    tmp_path,
    request,
) -> None:
    _clear_context_budget_env(monkeypatch)
    model_factory = PressureHarnessModelFactory(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_large_range",
                        "name": "artifact.range",
                        "args": {
                            "artifact_id": "art_pressure_large_text",
                            "start_line": 1,
                            "end_line": 500,
                        },
                    }
                ],
            },
            {"content": "large observation handled", "tool_calls": []},
        ],
        context_window_tokens=100_000,
    )
    client, repositories, model_factory = _build_v3_pressure_client(
        monkeypatch, model_factory
    )
    _start_runtime_command_client(client, request)

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_pressure_tool_result",
            "project_id": "proj_001",
            "objective": "Pressure test tool-result artifactization",
        },
    )
    assert created.status_code == 200
    _seed_large_text_artifact(repositories, "sess_pressure_tool_result", tmp_path)

    message = client.post(
        "/v3/sessions/sess_pressure_tool_result/messages",
        json={"message": "Read the large artifact and summarize what matters."},
    )
    assert message.status_code == 200

    drained = _admit_and_observe_runtime_command(
        client,
        session_id="sess_pressure_tool_result",
        request={"max_steps_per_agent": 3},
    )
    assert drained.status_code == 202
    payload = drained.json()
    event_types = [event["event_type"] for event in payload["events"]]
    invoker = model_factory.invokers["v3_harness_loop"]

    assert payload["status"] == "completed"
    assert payload["outputs"] == ["large observation handled"]
    assert len(invoker.calls) == 2
    assert "tool_result.artifactized" in event_types
    assert "llm.context_budget.exceeded" not in event_types
    assert _tool_message_name(invoker.calls[1]["messages"][-1]) == "artifact.range"
    observation_envelope = json.loads(_message_content(invoker.calls[1]["messages"][-1]))
    observation = observation_envelope["payload"]
    assert observation_envelope["ok"] is False
    assert observation["status"] == "tool_result_context_over_budget"
    assert observation["original_tool_ok"] is True
    assert "artifact_id" in observation
    assert "stress-observation-" not in _message_content(invoker.calls[1]["messages"][-1])

    artifacts = [
        artifact
        for artifact in repositories.artifacts.list_by_session(
            "sess_pressure_tool_result"
        )
        if artifact.kind is ArtifactKind.RESULT
        and artifact.relative_path == "tool_results/call_large_range.json"
    ]
    assert len(artifacts) == 1
    assert artifacts[0].artifact_id == observation["artifact_id"]
    document = repositories.engine_documents.get(
        str(dict(artifacts[0].metadata or {})["output_ref"])
    )
    assert document is not None
    assert document.document_kind == "tool_result_full"
    persisted_result = document.payload["tool_result"]
    assert document.payload["original_tool_ok"] is True
    assert "stress-observation-" in persisted_result["content"]


def test_v3_llm_response_event_is_available_before_message_command_finishes() -> None:
    repositories = _build_v3_engine_repositories()
    event_store = V3EventStore()
    model_factory = BlockingTraceModelFactory()
    service = V3HostApiService(
        repositories=repositories,
        event_store=event_store,
        model_factory=model_factory,
    )
    service.create_session(
        project_id="proj_001",
        session_id="sess_realtime_trace",
        title="Realtime trace",
        objective="Exercise realtime trace streaming.",
    )
    result_holder: dict[str, object] = {}
    error_holder: dict[str, BaseException] = {}

    service.post_message(
        session_id="sess_realtime_trace",
        message="create a task",
    )

    def _drain_runtime() -> None:
        try:
            result_holder["result"] = service.drain_runtime(
                session_id="sess_realtime_trace",
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            error_holder["error"] = exc

    thread = threading.Thread(target=_drain_runtime)
    thread.start()
    try:
        assert model_factory.entered_second_call.wait(timeout=5)
        realtime_events = event_store.list("sess_realtime_trace")
        trace_events = [
            event
            for event in realtime_events
            if event["event_type"] == "llm.response.created"
        ]
        assert trace_events
        assert (
            trace_events[0]["payload"]["response_text"]
            == "I will create a task before answering."
        )
        assert trace_events[0]["payload"]["tool_calls"][0]["tool_name"] == "task.create"
        assert "result" not in result_holder
    finally:
        model_factory.release_second_call.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    if error_holder:
        raise error_holder["error"]
    completed_events = event_store.list("sess_realtime_trace")
    trace_ids = [
        event["payload"]["trace_id"]
        for event in completed_events
        if event["event_type"] == "llm.response.created"
    ]
    assert len(trace_ids) == len(set(trace_ids))
    assert "result" in result_holder


def test_v3_engine_backed_research_execution_report_draft_loop(
    monkeypatch,
    request,
    tmp_path: Path,
) -> None:
    client, v3_repositories, model_factory = _build_v3_engine_llm_client(monkeypatch)
    _start_runtime_command_client(client, request)

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_engines",
            "project_id": "proj_001",
            "objective": "Evaluate a thermostability candidate and publish the final report",
        },
    )
    assert created.status_code == 200
    _seed_v3_execution_artifact(
        v3_repositories,
        "sess_v3_engines",
        tmp_path=tmp_path,
    )
    lane = client.post(
        "/v3/lanes",
        json={
            "session_id": "sess_v3_engines",
            "lane_id": "lane_v3_engines",
            "name": "engine lane",
            "cwd": "/tmp/openzyme-v3-engines",
        },
    )
    assert lane.status_code == 200

    research_task = client.post(
        "/v3/tasks",
        json={
            "session_id": "sess_v3_engines",
            "task_id": "task_research_v3",
            "subject": "Collect evidence",
            "description": "Collect papers for the scaffold family.",
            "kind": "research",
            "lane_id": "lane_v3_engines",
        },
    )
    assert research_task.status_code == 200
    research = client.post(
        "/v3/sessions/sess_v3_engines/messages",
        json={"message": "Run the research task.", "task_id": "task_research_v3"},
    )
    assert research.status_code == 200
    research_payload = research.json()
    assert research_payload["status"] == "completed"
    assert research_payload["outputs"] == []
    assert (
        research_payload["workspace"]["task_board"]["items"][0]["task"]["status"]
        == "todo"
    )
    assert "v3_teammate_loop:researcher" not in model_factory.invokers

    research_drain = _admit_and_observe_runtime_command(
        client,
        session_id="sess_v3_engines",
    )
    assert research_drain.status_code == 202
    research_payload = research_drain.json()
    assert research_payload["status"] == "completed"
    assert (
        research_payload["workspace"]["task_board"]["items"][0]["task"]["status"]
        == "completed"
    )
    assert (
        research_payload["workspace"]["capabilities"]["deep_research"][0][
            "canonical_summary"
        ]["status"]
        == "completed"
    )
    assert any(
        agent["agent"]["role"] == "researcher"
        for agent in research_payload["workspace"]["delegation"]["agents"]
    )
    research_assistant_messages = [
        message["content"]
        for message in research_payload["workspace"]["conversation"]
        if message["role"] == "assistant"
    ]
    assert "Research complete." in research_payload["outputs"]
    assert "Research complete." in research_assistant_messages

    execution_task = client.post(
        "/v3/tasks",
        json={
            "session_id": "sess_v3_engines",
            "task_id": "task_execution_v3",
            "subject": "Run fpocket",
            "description": "Run fpocket against the candidate structure.",
            "kind": "execution",
            "lane_id": "lane_v3_engines",
        },
    )
    assert execution_task.status_code == 200
    execution = client.post(
        "/v3/sessions/sess_v3_engines/messages",
        json={"message": "Run the execution task.", "task_id": "task_execution_v3"},
    )
    assert execution.status_code == 200
    execution_payload = execution.json()
    assert execution_payload["status"] == "completed"
    assert execution_payload["outputs"] == []
    execution_item = next(
        item
        for item in execution_payload["workspace"]["task_board"]["items"]
        if item["task"]["task_id"] == "task_execution_v3"
    )
    assert execution_item["task"]["status"] == "todo"

    execution_drain = _admit_and_observe_runtime_command(
        client,
        session_id="sess_v3_engines",
    )
    assert execution_drain.status_code == 202
    execution_payload = execution_drain.json()
    assert execution_payload["status"] == "waiting_approval"
    pending = execution_payload["workspace"]["pending_approvals"]
    assert pending[0]["kind"] == "execution_pipeline_plan"
    assert (
        execution_payload["workspace"]["capabilities"]["execution"][0]["status"]
        == "waiting_approval"
    )
    assert (
        execution_payload["workspace"]["conversation"][-1]["content"]
        == "Delegated execution task task_execution_v3."
    )
    assert not any(
        event["event_type"] == "conversation.assistant_message"
        for event in execution_payload["events"]
    )
    assert any(
        agent["agent"]["role"] == "executor"
        for agent in execution_payload["workspace"]["delegation"]["agents"]
    )
    master_calls_before_approval = model_factory.invokers["v3_harness_loop"].calls
    executor_calls_before_approval = model_factory.invokers[
        "v3_teammate_loop:executor"
    ].calls

    approval_id = pending[0]["approval_id"]
    resolved = client.post(
        f"/v3/approvals/{approval_id}/resolve",
        json={"decision": "approved"},
    )
    assert resolved.status_code == 200
    resolved_payload = resolved.json()
    assert (
        model_factory.invokers["v3_harness_loop"].calls
        == master_calls_before_approval
    )
    assert (
        model_factory.invokers["v3_teammate_loop:executor"].calls
        == executor_calls_before_approval
    )
    assert resolved_payload["status"] == "completed"
    assert resolved_payload["workspace"]["pending_approvals"] == []
    assert resolved_payload["outputs"] == []

    execution_resume = _admit_and_observe_runtime_command(
        client,
        session_id="sess_v3_engines",
    )
    assert execution_resume.status_code == 202
    resolved_payload = execution_resume.json()
    assert (
        model_factory.invokers["v3_harness_loop"].calls
        == master_calls_before_approval + 1
    )
    assert (
        model_factory.invokers["v3_teammate_loop:executor"].calls
        == executor_calls_before_approval + 2
    )
    executor_agent = next(
        agent
        for agent in v3_repositories.agents.list_by_session("sess_v3_engines")
        if agent.role == "executor"
    )
    assert any(
        message.message_type == "delegation_result"
        and message.sender == executor_agent.agent_id
        for message in v3_repositories.inbox.list_by_session("sess_v3_engines")
    )
    assert resolved_payload["status"] == "completed"
    assert resolved_payload["workspace"]["pending_approvals"] == []
    assert (
        resolved_payload["workspace"]["capabilities"]["execution"][0]["status"]
        == "succeeded"
    )
    assert resolved_payload["workspace"]["artifacts"]
    assert any("fpocket found" in output for output in resolved_payload["outputs"])
    assert any("Output artifacts:" in output for output in resolved_payload["outputs"])
    assert not any("Pipeline sandbox completed." in output for output in resolved_payload["outputs"])
    assert (
        "Protocol threads available via protocol.thread"
        in model_factory.invokers["v3_harness_loop"].system_prompts[-1]
    )
    conversation = resolved_payload["workspace"]["conversation"]
    assistant_messages = [
        message["content"] for message in conversation if message["role"] == "assistant"
    ]
    assert not any(
        message == "Execution finished: Pipeline sandbox completed."
        for message in assistant_messages
    )
    assert sum("fpocket found" in message for message in assistant_messages) == 1
    assert not any(
        "Approval resolved. The delegated execution task resumed" in message
        for message in assistant_messages
    )
    assert any(
        agent["agent"]["status"] == "idle"
        for agent in resolved_payload["workspace"]["delegation"]["agents"]
    )

    events = client.get("/v3/sessions/sess_v3_engines/events?replay=1")
    assert events.status_code == 200
    assert "event: engine.invocation.started" in events.text


def test_v3_message_ingress_uses_llm_driver_when_model_factory_is_available(
    monkeypatch,
    request,
) -> None:
    client, _ = _build_v3_llm_client(monkeypatch)
    _start_runtime_command_client(client, request)

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_llm",
            "project_id": "proj_001",
            "objective": "Capture the user's design goal",
        },
    )
    assert created.status_code == 200

    message = client.post(
        "/v3/sessions/sess_v3_llm/messages",
        json={"message": "Please track extracting the design goals as a task."},
    )
    assert message.status_code == 200
    payload = message.json()
    assert payload["outputs"] == []
    drained = _admit_and_observe_runtime_command(
        client,
        session_id="sess_v3_llm",
    )
    assert drained.status_code == 202
    payload = drained.json()
    assert payload["outputs"] == ["Created task task_llm_001 and captured the goal."]
    assert (
        payload["workspace"]["task_board"]["items"][0]["task"]["task_id"]
        == "task_llm_001"
    )
    assert (
        payload["workspace"]["conversation"][0]["content"]
        == "Please track extracting the design goals as a task."
    )
    assert (
        payload["workspace"]["conversation"][1]["content"]
        == "Created task task_llm_001 and captured the goal."
    )
    assert any(event["event_type"] == "tool.completed" for event in payload["events"])
    assert not any(
        agent["agent"]["role"] != "master"
        for agent in payload["workspace"]["delegation"]["agents"]
    )


def test_debug_llm_calls_endpoint_lists_details_and_clears_records(
    monkeypatch,
    request,
) -> None:
    get_llm_debug_recorder().clear()
    client, foundation = _build_client(monkeypatch)
    debug_client = TestClient(
        create_app(
                HostApiDependencies(
                    foundation=replace(
                        foundation, model_factory=DebugRecordingModelFactory()
                    ),
                    security_policy=_local_test_security(),
                    v3_background_runtime_enabled=False,
                )
        )
    )
    _start_runtime_command_client(debug_client, request)

    created = debug_client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_debug",
            "project_id": "proj_001",
            "objective": "Debug LLM calls",
        },
    )
    assert created.status_code == 200

    message = debug_client.post(
        "/v3/sessions/sess_v3_debug/messages",
        json={"message": "hello debug"},
    )
    assert message.status_code == 200
    drained = _admit_and_observe_runtime_command(
        debug_client,
        session_id="sess_v3_debug",
    )
    assert drained.status_code == 202

    records = debug_client.get("/debug/llm-calls?session_id=sess_v3_debug").json()
    assert len(records) == 1
    assert records[0]["purpose"] == "v3_harness_loop"
    assert records[0]["kind"] == "tool_calling"
    assert records[0]["request_context"]["session_id"] == "sess_v3_debug"
    assert records[0]["request"]["system_prompt"].startswith(
        "You are the top-level OpenZyme master agent."
    )
    assert records[0]["response"]["content"] == "Debug response."

    detail = debug_client.get(f"/debug/llm-calls/{records[0]['debug_id']}")
    assert detail.status_code == 200
    assert detail.json()["debug_id"] == records[0]["debug_id"]

    clear = debug_client.post("/debug/llm-calls/clear")
    assert clear.status_code == 200
    assert debug_client.get("/debug/llm-calls").json() == []


def test_v3_project_sessions_lists_recent_sessions_with_preview_and_pending_count(
    monkeypatch,
    request,
) -> None:
    client, _ = _build_v3_llm_client(monkeypatch)
    _start_runtime_command_client(client, request)

    created_a = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_list_a",
            "project_id": "proj_001",
            "objective": "First session",
            "title": "Session A",
        },
    )
    created_b = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_list_b",
            "project_id": "proj_001",
            "objective": "Second session",
            "title": "Session B",
        },
    )
    assert created_a.status_code == 200
    assert created_b.status_code == 200

    message = client.post(
        "/v3/sessions/sess_v3_list_a/messages",
        json={"message": "Please track extracting the design goals as a task."},
    )
    assert message.status_code == 200
    drained = _admit_and_observe_runtime_command(
        client,
        session_id="sess_v3_list_a",
    )
    assert drained.status_code == 202

    listing = client.get("/v3/projects/proj_001/sessions")
    assert listing.status_code == 200
    payload = listing.json()
    assert [item["session_id"] for item in payload] == [
        "sess_v3_list_a",
        "sess_v3_list_b",
    ]
    assert payload[0]["title"] == "Session A"
    assert (
        payload[0]["latest_message_preview"]
        == "Created task task_llm_001 and captured the goal."
    )
    assert payload[0]["pending_approval_count"] == 0
    assert payload[0]["updated_at"] >= payload[1]["updated_at"]


def test_v3_message_ingress_returns_service_unavailable_without_model_factory(
    monkeypatch,
) -> None:
    client, _ = _build_client(monkeypatch, with_model_factory=False)

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_v3_missing_llm",
            "project_id": "proj_001",
            "objective": "Capture the user's design goal",
        },
    )
    assert created.status_code == 200

    message = client.post(
        "/v3/sessions/sess_v3_missing_llm/messages",
        json={"message": "Please track extracting the design goals as a task."},
    )
    assert message.status_code == 200
    payload = message.json()
    assert payload["outputs"] == []
    assert any(
        event["event_type"] == "signal.queued"
        and event["payload"]["agent_id"] == "agent:master"
        for event in payload["events"]
    )
