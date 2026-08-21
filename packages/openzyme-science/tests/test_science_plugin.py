from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from importlib.resources import files
import importlib.metadata
from typing import Any

import pytest

from openzyme_contracts import EvidenceKind
from openzyme_contracts import EvidenceRef
from openzyme_contracts import ToolInvocation
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import ExtensionStateCommand
from openzyme_extension_spi import ExtensionStateRecord
from openzyme_extension_spi import HttpRouteInvocation
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelEntitySnapshot
from openzyme_extension_spi import KernelQueryContext
from openzyme_extension_spi import ProjectionRequest
from openzyme_extension_spi import WorkerClaimRequest
from openzyme_extension_spi import parse_component_manifest_json
from openzyme_science import SCIENCE_CLOSURE_EVIDENCE_CONTRACT_ID
from openzyme_science import SCIENCE_COLLECTIONS
from openzyme_science import SCIENCE_COMPONENT_MANIFEST_DIGEST
from openzyme_science import SCIENCE_PROJECTION_CONTRACT_DIGEST
from openzyme_science import SCIENCE_RENDERER_CONTRACT_DIGEST
from openzyme_science import SCIENCE_STATE_NAMESPACE
from openzyme_science import SCIENCE_TOOL_SPECS
from openzyme_science import ScienceFinishValidator
from openzyme_science import ScienceExtensionStateProjectionApplication
from openzyme_science import ScienceHttpRouteRuntime
from openzyme_science import ScienceLifecycleToolApplication
from openzyme_science import ScienceProjectionContributor
from openzyme_science import ScienceStateMutationApplication
from openzyme_science import ScienceToolRuntime
from openzyme_science import ScienceTransactionParticipant
from openzyme_science import ScienceUiRenderer
from openzyme_science import build_science_plugin_runtime_surfaces
from openzyme_science import locate_component_manifest


DIGEST = "sha256:" + "1" * 64


def _query_context(*, session_id: str = "session-1") -> KernelQueryContext:
    return KernelQueryContext(
        session_id=session_id,
        actor_id="agent-1",
        owner_plugin_id="openzyme.science",
        authority_lease_id="lease-1",
        extension_bundle_digest=DIGEST,
        capability_binding_digest=DIGEST,
        correlation_id="correlation-1",
    )


def _command_context(*, session_id: str = "session-1") -> KernelCommandContext:
    return KernelCommandContext(
        command_id="command-1",
        session_id=session_id,
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
    )


def test_science_manifest_and_runtime_surfaces_are_exact() -> None:
    locator = locate_component_manifest()
    manifest = parse_component_manifest_json(
        files(locator.resource_package)
        .joinpath(locator.resource_name)
        .read_text(encoding="utf-8")
    )

    class Application:
        pass

    runtime = build_science_plugin_runtime_surfaces(
        tool_application=Application(),
        http_application=Application(),
        projection_application=Application(),
        worker_application=Application(),
        evidence_reader=Application(),
    )

    assert locator.manifest_digest == SCIENCE_COMPONENT_MANIFEST_DIGEST
    assert manifest.manifest_digest == SCIENCE_COMPONENT_MANIFEST_DIGEST
    assert manifest.state_namespace == SCIENCE_STATE_NAMESPACE
    assert {item.contract.tool_name for item in manifest.tools} == {
        item.tool_name for item in SCIENCE_TOOL_SPECS
    }
    assert {item.runtime_id for item in manifest.tools} == {
        item.runtime_id for item in runtime.tools
    }
    assert runtime.projections[0].section_contract_digest == (
        SCIENCE_PROJECTION_CONTRACT_DIGEST
    )
    assert manifest.ui_renderers[0].contract_digest == SCIENCE_RENDERER_CONTRACT_DIGEST
    assert {item.route_id for item in runtime.http_routes} == {
        item.route_id for item in manifest.http_routes
    }
    assert {item.participant_id for item in runtime.transaction_participants} == {
        item.contribution_id for item in manifest.transaction_participants
    }
    requirements = importlib.metadata.requires("openzyme-science") or []
    assert all("openzyme-core" not in requirement for requirement in requirements)


@dataclass
class _ToolApplication:
    calls: int = 0

    def invoke(self, *, invocation: ToolInvocation):
        self.calls += 1
        if invocation.arguments.get("reject"):
            raise ValueError("cross-attempt command rejected")
        return {"state": "accepted"}


def test_science_tool_never_finishes_task_or_performs_fallback() -> None:
    application = _ToolApplication()
    spec = next(
        item
        for item in SCIENCE_TOOL_SPECS
        if item.tool_name == "scientific.attempt.close"
    )
    runtime = ScienceToolRuntime(spec, application)
    invocation = ToolInvocation(
        call_id="call-1",
        tool_name=spec.tool_name,
        arguments={
            "attempt_id": "attempt-1",
            "selection_id": "selection-1",
            "idempotency_key": "close-1",
        },
        session_id="session-1",
        agent_member_id="agent-1",
        task_id="task-1",
    )

    result = runtime.invoke(invocation)

    assert result.ok is True
    assert result.payload["task_finished"] is False
    assert result.payload["fallback_performed"] is False
    assert application.calls == 1


class _State:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], ExtensionStateRecord] = {}

    def get(self, *, namespace: str, entity_kind: str, entity_id: str):
        assert namespace == SCIENCE_STATE_NAMESPACE
        return self.records.get((entity_kind, entity_id))

    def list(self, **_: Any):
        return ()

    def upsert(self, mutation):
        current = self.records.get((mutation.entity_kind, mutation.entity_id))
        if current is None:
            assert mutation.expected_state_version is None
            state_version = 1
        else:
            assert mutation.expected_state_version == current.state_version
            state_version = current.state_version + 1
        record = ExtensionStateRecord(
            namespace=mutation.namespace,
            entity_kind=mutation.entity_kind,
            entity_id=mutation.entity_id,
            state_version=state_version,
            payload=mutation.payload,
            record_digest=canonical_sha256_digest(mutation.to_dict()),
        )
        self.records[(record.entity_kind, record.entity_id)] = record
        return record

    def delete(self, mutation):
        raise AssertionError(f"unexpected delete: {mutation}")


def _state_command(
    *,
    record: dict[str, Any],
    entity_kind: str = "attempt",
    entity_id: str = "attempt-1",
) -> ExtensionStateCommand:
    participant = ScienceTransactionParticipant()
    return ExtensionStateCommand(
        context=_command_context(),
        participant_id=participant.participant_id,
        namespace=participant.state_namespace,
        operation="upsert_science_record",
        payload={
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "expected_state_version": None,
            "record": record,
        },
    )


def test_science_transaction_is_namespace_confined_and_session_bound() -> None:
    participant = ScienceTransactionParticipant()
    state = _State()
    plan = participant.prepare(
        _state_command(
            record={
                "session_id": "session-1",
                "attempt_id": "attempt-1",
                "attempt_generation": 1,
                "state": "open",
            }
        ),
        state,
    )
    result = participant.apply(plan, state)

    assert result.mutation_applied is True
    assert result.result["task_finished"] is False
    assert len(plan.mutations) == 1

    with pytest.raises(ValueError, match="crossed its Session"):
        participant.prepare(
            _state_command(
                record={
                    "session_id": "session-2",
                    "attempt_id": "attempt-1",
                    "attempt_generation": 1,
                    "state": "open",
                }
            ),
            _State(),
        )
    with pytest.raises(ValueError, match="private or retired file-era"):
        participant.prepare(
            _state_command(
                record={
                    "session_id": "session-1",
                    "attempt_id": "attempt-1",
                    "attempt_generation": 1,
                    "state": "open",
                    "artifact_id": "legacy-1",
                }
            ),
            _State(),
        )


def test_science_transaction_rejects_cross_attempt_and_generation() -> None:
    participant = ScienceTransactionParticipant()
    state = _State()
    attempt_command = _state_command(
        record={
            "session_id": "session-1",
            "attempt_id": "attempt-1",
            "attempt_generation": 2,
            "state": "open",
        }
    )
    state.upsert(participant.prepare(attempt_command, state).mutations[0])

    with pytest.raises(ValueError, match="attempt generation"):
        participant.prepare(
            _state_command(
                entity_kind="selection",
                entity_id="selection-1",
                record={
                    "session_id": "session-1",
                    "selection_id": "selection-1",
                    "attempt_id": "attempt-1",
                    "attempt_generation": 1,
                    "state": "open",
                },
            ),
            state,
        )

    with pytest.raises(ValueError, match="unknown attempt"):
        participant.prepare(
            _state_command(
                entity_kind="selection",
                entity_id="selection-2",
                record={
                    "session_id": "session-1",
                    "selection_id": "selection-2",
                    "attempt_id": "attempt-2",
                    "attempt_generation": 2,
                    "state": "open",
                },
            ),
            state,
        )


@dataclass
class _KernelExtensionStateApplication:
    calls: int = 0
    state: _State = field(default_factory=_State)

    def execute(self, command: ExtensionStateCommand):
        self.calls += 1
        participant = ScienceTransactionParticipant()
        plan = participant.prepare(command, self.state)
        return participant.apply(plan, self.state)


def test_science_mutation_gateway_requires_kernel_context_and_restricted_participant() -> None:
    kernel = _KernelExtensionStateApplication()
    application = ScienceStateMutationApplication(kernel)

    result = application.upsert_record(
        context=_command_context(),
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
    assert kernel.calls == 1

    with pytest.raises(ValueError, match="another Plugin"):
        application.upsert_record(
            context=replace(_command_context(), owner_plugin_id="other.plugin"),
            entity_kind="attempt",
            entity_id="attempt-1",
            expected_state_version=None,
            record={
                "session_id": "session-1",
                "attempt_id": "attempt-1",
                "attempt_generation": 1,
            },
        )


@dataclass
class _InvocationContexts:
    session_id: str = "session-1"
    actor_id: str = "agent-1"
    calls: int = 0

    def resolve(self, *, invocation: ToolInvocation, idempotency_key: str):
        self.calls += 1
        return replace(
            _command_context(session_id=self.session_id),
            actor_id=self.actor_id,
            idempotency_key=idempotency_key,
            command_id=f"command-{self.calls}",
        )


@dataclass
class _ScienceStateQuery:
    state: _State

    def get_session_record(
        self,
        *,
        namespace: str,
        session_id: str,
        entity_kind: str,
        entity_id: str,
    ):
        assert namespace == SCIENCE_STATE_NAMESPACE
        record = self.state.records.get((entity_kind, entity_id))
        if record is None or record.payload.get("session_id") != session_id:
            return None
        return record


def _tool_invocation(tool_name: str, arguments: dict[str, Any]) -> ToolInvocation:
    return ToolInvocation(
        call_id=f"call-{tool_name}",
        tool_name=tool_name,
        arguments=arguments,
        session_id="session-1",
        agent_member_id="agent-1",
        task_id="task-1",
    )


def test_science_lifecycle_tools_use_only_restricted_participant_state() -> None:
    kernel = _KernelExtensionStateApplication()
    mutation = ScienceStateMutationApplication(kernel)
    mutation.upsert_record(
        context=_command_context(),
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
    application = ScienceLifecycleToolApplication(
        mutation=mutation,
        state=_ScienceStateQuery(kernel.state),
        contexts=_InvocationContexts(),
    )

    selection = application.invoke(
        invocation=_tool_invocation(
            "scientific.selection.begin",
            {"attempt_id": "attempt-1", "idempotency_key": "selection-1"},
        )
    )
    selection_id = str(selection["entity_id"])
    application.invoke(
        invocation=_tool_invocation(
            "scientific.operation.adopt",
            {
                "selection_id": selection_id,
                "operation_id": "operation-1",
                "workflow_role": "primary_result",
                "reason_code": "owner_selected",
                "idempotency_key": "adoption-1",
            },
        )
    )
    sealed = application.invoke(
        invocation=_tool_invocation(
            "scientific.selection.seal",
            {
                "selection_id": selection_id,
                "expected_universe_digest": DIGEST,
                "idempotency_key": "seal-1",
            },
        )
    )
    closed = application.invoke(
        invocation=_tool_invocation(
            "scientific.attempt.close",
            {
                "attempt_id": "attempt-1",
                "selection_id": selection_id,
                "idempotency_key": "close-1",
            },
        )
    )

    assert sealed["state"] == "sealed"
    assert closed["state"] == "closed"
    assert closed["task_finished"] is False
    assert {record.namespace for record in kernel.state.records.values()} == {
        SCIENCE_STATE_NAMESPACE
    }
    assert kernel.calls == 5


def test_science_lifecycle_tool_rejects_cross_session_kernel_context() -> None:
    application = ScienceLifecycleToolApplication(
        mutation=ScienceStateMutationApplication(_KernelExtensionStateApplication()),
        state=_ScienceStateQuery(_State()),
        contexts=_InvocationContexts(session_id="session-2"),
    )

    with pytest.raises(ValueError, match="crossed its Session"):
        application.invoke(
            invocation=_tool_invocation(
                "scientific.selection.begin",
                {"attempt_id": "attempt-1", "idempotency_key": "selection-1"},
            )
        )


@dataclass
class _ProjectionApplication:
    payload: dict[str, Any]

    def project(self, **_: Any):
        return self.payload, None

    def inspect_session(self, **_: Any):
        return self.payload


def test_science_projection_and_http_route_reject_private_locators() -> None:
    application = _ProjectionApplication({"attempts": [{"host_path": "/private"}]})
    contributor = ScienceProjectionContributor(application)
    request = ProjectionRequest(
        context=_query_context(),
        section_id="openzyme.science@1",
        max_items=20,
        max_bytes=16_384,
    )

    with pytest.raises(ValueError, match="private or retired file-era"):
        contributor.project(request)
    with pytest.raises(ValueError, match="private or retired file-era"):
        ScienceHttpRouteRuntime(application).invoke(
            HttpRouteInvocation(
                context=_query_context(),
                route_id="openzyme.science.http.session-view@1",
                method="GET",
                path="/v3/extensions/openzyme.science/sessions/session-1",
                payload={},
            )
        )


@dataclass
class _ProjectionStateQuery:
    records: tuple[ExtensionStateRecord, ...]
    next_cursor: str | None = None
    calls: list[dict[str, Any]] | None = None

    def list_session_records(self, **arguments: Any):
        if self.calls is not None:
            self.calls.append(dict(arguments))
        return self.records, self.next_cursor


def _science_state_record(
    *,
    entity_kind: str,
    entity_id: str,
    session_id: str = "session-1",
    payload: dict[str, Any] | None = None,
) -> ExtensionStateRecord:
    values = {
        "session_id": session_id,
        "state": "open",
        **({} if payload is None else payload),
    }
    return ExtensionStateRecord(
        namespace=SCIENCE_STATE_NAMESPACE,
        entity_kind=entity_kind,
        entity_id=entity_id,
        state_version=1,
        payload=values,
        record_digest=canonical_sha256_digest(
            {
                "namespace": SCIENCE_STATE_NAMESPACE,
                "entity_kind": entity_kind,
                "entity_id": entity_id,
                "state_version": 1,
                "payload": values,
            }
        ),
    )


def test_science_extension_state_projection_is_namespaced_bounded_and_read_only() -> None:
    calls: list[dict[str, Any]] = []
    query = _ProjectionStateQuery(
        records=(
            _science_state_record(
                entity_kind="attempt",
                entity_id="attempt-1",
                payload={"attempt_generation": 2},
            ),
            _science_state_record(
                entity_kind="selection",
                entity_id="selection-1",
                payload={"attempt_id": "attempt-1", "attempt_generation": 2},
            ),
        ),
        next_cursor="cursor-2",
        calls=calls,
    )
    application = ScienceExtensionStateProjectionApplication(query)

    payload, next_cursor = application.project(
        session_id="session-1",
        actor_id="agent-1",
        max_items=20,
        cursor="cursor-1",
    )

    assert set(payload) == {
        *(collection for _, collection in SCIENCE_COLLECTIONS),
        "task_finished",
    }
    assert payload["attempts"][0]["entity_id"] == "attempt-1"
    assert payload["selections"][0]["entity_id"] == "selection-1"
    assert payload["task_finished"] is False
    assert next_cursor == "cursor-2"
    assert calls == [
        {
            "namespace": SCIENCE_STATE_NAMESPACE,
            "session_id": "session-1",
            "entity_kinds": tuple(kind for kind, _ in SCIENCE_COLLECTIONS),
            "after_cursor": "cursor-1",
            "limit": 20,
        }
    ]

    core_state = {"tasks": [{"task_id": "task-1", "status": "in_progress"}]}
    rendered = ScienceUiRenderer().render(payload)
    assert rendered["attempts_count"] == 1
    assert rendered["selections_count"] == 1
    assert rendered["task_finished"] is False
    assert core_state == {
        "tasks": [{"task_id": "task-1", "status": "in_progress"}]
    }


def test_science_projection_rejects_cross_session_and_renderer_contract_drift() -> None:
    application = ScienceExtensionStateProjectionApplication(
        _ProjectionStateQuery(
            records=(
                _science_state_record(
                    entity_kind="attempt",
                    entity_id="attempt-2",
                    session_id="session-2",
                ),
            )
        )
    )

    with pytest.raises(ValueError, match="crossed its Session"):
        application.project(
            session_id="session-1",
            actor_id="agent-1",
            max_items=20,
            cursor=None,
        )

    with pytest.raises(ValueError, match="contract drifted"):
        ScienceUiRenderer().render(
            {
                **{
                    collection: [] for _, collection in SCIENCE_COLLECTIONS
                },
                "task_finished": True,
            }
        )


@dataclass
class _EvidenceReader:
    accepted: bool
    calls: int = 0

    def validate_closure(self, **_: Any):
        self.calls += 1
        return self.accepted, (() if self.accepted else ("scientific_closure_invalid",))


def _task_snapshot() -> KernelEntitySnapshot:
    return KernelEntitySnapshot(
        entity=KernelEntityRef(
            entity_kind="task",
            entity_id="task-1",
            state_version=1,
            entity_digest=DIGEST,
        ),
        payload={},
    )


def _evidence(*, session_id: str = "session-1") -> EvidenceRef:
    return EvidenceRef(
        evidence_id="evidence-1",
        evidence_kind=EvidenceKind.EXTENSION,
        contract_id=SCIENCE_CLOSURE_EVIDENCE_CONTRACT_ID,
        owner_component_id="openzyme.science",
        project_id="project-1",
        session_id=session_id,
        task_id="task-1",
        subject_ref="closure-1",
        subject_digest=DIGEST,
        attributes={"attempt_id": "attempt-1", "selection_id": "selection-1"},
    )


def test_finish_validator_is_read_only_and_requires_exact_session_evidence() -> None:
    reader = _EvidenceReader(True)
    accepted = ScienceFinishValidator(reader).validate(
        _query_context(), _task_snapshot(), (_evidence(),)
    )
    rejected = ScienceFinishValidator(reader).validate(
        _query_context(), _task_snapshot(), (_evidence(session_id="session-2"),)
    )

    assert accepted.accepted is True
    assert accepted.rejection_codes == ()
    assert rejected.accepted is False
    assert rejected.rejection_codes == ("scientific_closure_missing_or_ambiguous",)
    assert reader.calls == 1


def test_science_worker_claim_does_not_imply_task_completion() -> None:
    class WorkerApplication:
        def claim(self, request):
            raise AssertionError(f"unexpected claim: {request}")

        def run(self, claim):
            raise AssertionError(f"unexpected run: {claim}")

    runtime = build_science_plugin_runtime_surfaces(
        tool_application=_ToolApplication(),
        http_application=_ProjectionApplication({}),
        projection_application=_ProjectionApplication({}),
        worker_application=WorkerApplication(),
        evidence_reader=_EvidenceReader(True),
    )
    claims = runtime.workers[0].claim(
        WorkerClaimRequest(
            owner_plugin_id="another.plugin",
            worker_id="openzyme.science.worker@1",
            activation_epoch=1,
            max_items=1,
            lease_seconds=30,
        )
    )

    assert claims == ()
