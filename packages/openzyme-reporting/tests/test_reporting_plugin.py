from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import importlib.metadata
import json
from pathlib import Path
import tomllib
from typing import Any

import pytest

from openzyme_contracts import EvidenceKind
from openzyme_contracts import EvidenceRef
from openzyme_contracts import RevisionPathEntryKind
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import ToolInvocation
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import ExtensionStateCommand
from openzyme_extension_spi import ExtensionStateRecord
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelEntitySnapshot
from openzyme_extension_spi import KernelQueryContext
from openzyme_extension_spi import parse_component_manifest_json
from openzyme_reporting import REPORTING_COMPONENT_MANIFEST_DIGEST
from openzyme_reporting import REPORTING_REPORT_EVIDENCE_CONTRACT_ID
from openzyme_reporting import REPORTING_STATE_NAMESPACE
from openzyme_reporting import REPORTING_TOOL_SPECS
from openzyme_reporting import ReportFormat
from openzyme_reporting import ReportRenderReceipt
from openzyme_reporting import ReportRenderStatus
from openzyme_reporting import ReportValidationStatus
from openzyme_reporting import ReportVersion
from openzyme_reporting import ReportingFinishValidator
from openzyme_reporting import ReportingExtensionStateProjectionApplication
from openzyme_reporting import ReportingLifecycleToolApplication
from openzyme_reporting import ReportingStateMutationApplication
from openzyme_reporting import ReportingToolRuntime
from openzyme_reporting import ReportingTransactionParticipant
from openzyme_reporting import ReportingUiRenderer
from openzyme_reporting import locate_component_manifest


ZERO_DIGEST = "sha256:" + "0" * 64
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _content_ref(*, entry_kind: RevisionPathEntryKind = RevisionPathEntryKind.FILE):
    values: dict[str, Any] = {
        "ref_id": "ref-1",
        "publication_id": "publication-1",
        "project_id": "project-1",
        "session_id": "session-1",
        "repository_binding_id": "binding-1",
        "repository_binding_version": 1,
        "repository_id": "repository-1",
        "commit": "a" * 40,
        "tree": "b" * 40,
        "path": "reports/final.md",
        "entry_kind": entry_kind,
        "object_id": "c" * 40,
        "size_bytes": 42 if entry_kind is not RevisionPathEntryKind.DIRECTORY else None,
        "lfs_oid": None,
        "lfs_size_bytes": None,
        "path_manifest_digest": ZERO_DIGEST if entry_kind is RevisionPathEntryKind.DIRECTORY else None,
        "created_at": "2026-08-20T00:00:00+00:00",
    }
    return RevisionPathRef.create(**values)


def _report() -> ReportVersion:
    return ReportVersion.create(
        report_id="report-1",
        project_id="project-1",
        session_id="session-1",
        task_id="task-1",
        owner_agent_member_id="agent-1",
        report_contract_id="enzymedesign.aox.report@1",
        report_version=1,
        report_format=ReportFormat.MARKDOWN,
        title="Final report",
        summary="Bounded metadata only.",
        content_ref=_content_ref(),
        supersedes_report_id=None,
        created_at="2026-08-20T00:00:00+00:00",
    )


def _query_context() -> KernelQueryContext:
    return KernelQueryContext(
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.reporting",
        authority_lease_id="lease-1",
        extension_bundle_digest=ZERO_DIGEST,
        capability_binding_digest=ZERO_DIGEST,
        correlation_id="correlation-1",
    )


def _command_context() -> KernelCommandContext:
    return KernelCommandContext(
        command_id="command-1",
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.reporting",
        authority_lease_id="lease-1",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=1,
        extension_bundle_digest=ZERO_DIGEST,
        capability_binding_digest=ZERO_DIGEST,
        idempotency_key="idempotency-1",
        correlation_id="correlation-1",
    )


def test_manifest_and_runtime_tool_catalog_are_exact() -> None:
    locator = locate_component_manifest()
    document = json.loads(
        (PACKAGE_ROOT / "src/openzyme_reporting/manifests/plugin.json").read_text()
    )
    manifest = parse_component_manifest_json(json.dumps(document))

    assert locator.manifest_digest == REPORTING_COMPONENT_MANIFEST_DIGEST
    assert manifest.manifest_digest == REPORTING_COMPONENT_MANIFEST_DIGEST
    assert {
        item.contract.tool_name: item.contract.to_dict() for item in manifest.tools
    } == {spec.tool_name: spec.to_dict() for spec in REPORTING_TOOL_SPECS}
    assert manifest.state_namespace == REPORTING_STATE_NAMESPACE
    assert [item.contribution_id for item in manifest.finish_validators] == [
        "openzyme.reporting.finish-validator@1"
    ]
    requirements = importlib.metadata.requires("openzyme-reporting") or []
    assert all("openzyme-core" not in requirement for requirement in requirements)


def test_report_version_is_revision_bound_and_rejects_directory() -> None:
    report = _report()
    before = report.to_dict()

    assert report.content_ref.path == "reports/final.md"
    assert report.to_dict() == before
    with pytest.raises(ValueError, match="immutable file"):
        ReportVersion.create(
            **{
                **report.identity_payload,
                "content_ref": _content_ref(
                    entry_kind=RevisionPathEntryKind.DIRECTORY
                ),
            }
        )


@dataclass
class _ToolApplication:
    calls: int = 0

    def invoke(self, *, invocation: ToolInvocation):
        self.calls += 1
        return {"state": "draft", "render_performed": False}


def test_tool_rejects_inline_body_before_application_and_never_finishes_task() -> None:
    application = _ToolApplication()
    spec = next(item for item in REPORTING_TOOL_SPECS if item.tool_name == "report.publish")
    runtime = ReportingToolRuntime(contract=spec, application=application)
    result = runtime.invoke(
        ToolInvocation(
            call_id="call-1",
            tool_name="report.publish",
            arguments={"markdown": "# private"},
            session_id="session-1",
            agent_member_id="agent-1",
            task_id="task-1",
        )
    )

    assert result.ok is False
    assert result.error_code == "report_body_inline_forbidden"
    assert result.payload["task_finished"] is False
    assert application.calls == 0


@dataclass
class _RendererCatalog:
    digest: str | None

    def contract_digest(self, renderer_id: str):
        assert renderer_id == "openzyme.reporting.renderer@1"
        return self.digest


def test_render_request_rejects_missing_or_drifted_renderer_before_application() -> None:
    application = _ToolApplication()
    spec = next(
        item for item in REPORTING_TOOL_SPECS if item.tool_name == "report.render.request"
    )
    invocation = ToolInvocation(
        call_id="call-render",
        tool_name=spec.tool_name,
        arguments={
            "report_id": "report-1",
            "report_digest": ZERO_DIGEST,
            "renderer_id": "openzyme.reporting.renderer@1",
            "renderer_contract_digest": ZERO_DIGEST,
            "output_format": "pdf",
        },
        session_id="session-1",
        agent_member_id="agent-1",
        task_id="task-1",
    )

    result = ReportingToolRuntime(
        contract=spec,
        application=application,
        renderer_catalog=_RendererCatalog(None),
    ).invoke(invocation)

    assert result.ok is False
    assert result.error_code == "report_renderer_missing_or_drifted"
    assert result.payload["task_finished"] is False
    assert application.calls == 0


def test_failed_renderer_receipt_has_no_output_or_task_transition() -> None:
    receipt = ReportRenderReceipt.create(
        render_id="render-1",
        report_id="report-1",
        session_id="session-1",
        source_report_digest=ZERO_DIGEST,
        renderer_id="openzyme.reporting.renderer@1",
        renderer_contract_digest=ZERO_DIGEST,
        status=ReportRenderStatus.FAILED,
        output_ref=None,
        failure_code="renderer_process_failed",
        created_at="2026-08-20T00:00:00+00:00",
    )

    assert receipt.to_dict()["fallback_performed"] is False
    assert receipt.to_dict()["task_finished"] is False
    with pytest.raises(ValueError, match="cannot expose an output"):
        ReportRenderReceipt.create(
            render_id="render-2",
            report_id="report-1",
            session_id="session-1",
            source_report_digest=ZERO_DIGEST,
            renderer_id="openzyme.reporting.renderer@1",
            renderer_contract_digest=ZERO_DIGEST,
            status=ReportRenderStatus.FAILED,
            output_ref=_content_ref(),
            failure_code="renderer_process_failed",
            created_at="2026-08-20T00:00:00+00:00",
        )


def test_standard_distribution_omits_reporting_plugin() -> None:
    document = tomllib.loads(
        (
            PACKAGE_ROOT.parents[1]
            / "distributions/openzyme-standard/openzyme-composition.toml"
        ).read_text()
    )

    assert document["plugins"]["required"] == []
    assert document["plugins"]["optional"] == []


class _State:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], ExtensionStateRecord] = {}

    def get(self, *, namespace: str, entity_kind: str, entity_id: str):
        assert namespace == REPORTING_STATE_NAMESPACE
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

    def get_session_record(
        self,
        *,
        namespace: str,
        session_id: str,
        entity_kind: str,
        entity_id: str,
    ):
        assert namespace == REPORTING_STATE_NAMESPACE
        record = self.records.get((entity_kind, entity_id))
        if record is None or record.payload.get("session_id") != session_id:
            return None
        return record

    def list_session_records(
        self,
        *,
        namespace: str,
        session_id: str,
        entity_kinds: tuple[str, ...],
        after_cursor: str | None,
        limit: int,
    ):
        assert namespace == REPORTING_STATE_NAMESPACE
        assert after_cursor is None
        records = tuple(
            record
            for key, record in sorted(self.records.items())
            if key[0] in entity_kinds
            and record.payload.get("session_id") == session_id
        )
        return records[:limit], None


def test_reporting_transaction_is_namespaced_and_body_free() -> None:
    participant = ReportingTransactionParticipant()
    state = _State()
    command = ExtensionStateCommand(
        context=_command_context(),
        participant_id=participant.participant_id,
        namespace=participant.state_namespace,
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

    plan = participant.prepare(command, state)
    result = participant.apply(plan, state)

    assert result.mutation_applied is True
    assert result.result["task_finished"] is False
    assert result.result["workspace_publication_performed"] is False

    with pytest.raises(ValueError, match="forbidden report body"):
        participant.prepare(
            ExtensionStateCommand(
                context=_command_context(),
                participant_id=participant.participant_id,
                namespace=participant.state_namespace,
                operation="upsert_reporting_records",
                payload={
                    "records": [
                        {
                            "entity_kind": "draft",
                            "entity_id": "draft-1",
                            "expected_state_version": None,
                            "record": {"body": "private"},
                        }
                    ]
                },
            ),
            _State(),
        )


@dataclass
class _KernelExtensionStateApplication:
    commands: list[ExtensionStateCommand]

    def execute(self, command: ExtensionStateCommand):
        self.commands.append(command)
        participant = ReportingTransactionParticipant()
        state = _State()
        return participant.apply(participant.prepare(command, state), state)


def test_reporting_state_mutation_uses_only_kernel_application_service() -> None:
    kernel = _KernelExtensionStateApplication(commands=[])
    application = ReportingStateMutationApplication(kernel=kernel)

    result = application.upsert_records(
        context=_command_context(),
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
    assert len(kernel.commands) == 1
    assert kernel.commands[0].namespace == REPORTING_STATE_NAMESPACE
    assert kernel.commands[0].context.owner_plugin_id == "openzyme.reporting"


@dataclass
class _EvidenceReader:
    report: ReportVersion | None
    status: ReportValidationStatus | None

    def get_report(self, report_id: str):
        return self.report if self.report is not None and report_id == self.report.report_id else None

    def validation_status(self, **_: Any):
        return self.status


def _task_snapshot(*, required_version: int = 1) -> KernelEntitySnapshot:
    return KernelEntitySnapshot(
        entity=KernelEntityRef(
            entity_kind="task",
            entity_id="task-1",
            state_version=1,
            entity_digest=ZERO_DIGEST,
        ),
        payload={
            "required_report_contract_id": "enzymedesign.aox.report@1",
            "required_report_version": required_version,
        },
    )


def _evidence(report: ReportVersion) -> EvidenceRef:
    return EvidenceRef(
        evidence_id="evidence-1",
        evidence_kind=EvidenceKind.EXTENSION,
        contract_id=REPORTING_REPORT_EVIDENCE_CONTRACT_ID,
        owner_component_id="openzyme.reporting",
        project_id="project-1",
        session_id="session-1",
        task_id="task-1",
        subject_ref=report.report_id,
        subject_digest=report.report_digest,
        attributes={"report_version": report.report_version},
    )


def test_finish_validator_is_read_only_and_requires_exact_validated_version() -> None:
    report = _report()
    accepted = ReportingFinishValidator(
        _EvidenceReader(report, ReportValidationStatus.ACCEPTED)
    ).validate(_query_context(), _task_snapshot(), (_evidence(report),))
    rejected = ReportingFinishValidator(_EvidenceReader(None, None)).validate(
        _query_context(),
        _task_snapshot(),
        (_evidence(report),),
    )
    wrong_version = ReportingFinishValidator(
        _EvidenceReader(report, ReportValidationStatus.ACCEPTED)
    ).validate(
        _query_context(),
        _task_snapshot(required_version=2),
        (_evidence(report),),
    )

    assert accepted.accepted is True
    assert accepted.rejection_codes == ()
    assert rejected.accepted is False
    assert rejected.rejection_codes == ("report_version_missing",)
    assert wrong_version.rejection_codes == ("report_version_mismatch",)


@dataclass
class _Contexts:
    session_id: str = "session-1"

    def resolve(self, *, invocation: ToolInvocation, idempotency_key: str):
        return replace(
            _command_context(),
            command_id=f"command-{idempotency_key}",
            session_id=self.session_id,
            actor_id=invocation.agent_member_id,
            idempotency_key=idempotency_key,
            correlation_id=invocation.call_id,
        )


@dataclass
class _Clock:
    value: str = "2026-08-21T00:00:00+00:00"

    def now(self) -> str:
        return self.value


@dataclass
class _SharedKernelExtensionStateApplication:
    state: _State

    def execute(self, command: ExtensionStateCommand):
        participant = ReportingTransactionParticipant()
        return participant.apply(participant.prepare(command, self.state), self.state)


def _invoke(
    application: ReportingLifecycleToolApplication,
    tool_name: str,
    arguments: dict[str, Any],
):
    return application.invoke(
        invocation=ToolInvocation(
            call_id=f"call-{tool_name}",
            tool_name=tool_name,
            arguments=arguments,
            session_id="session-1",
            agent_member_id="agent-1",
            task_id="task-1",
        )
    )


def test_target_reporting_application_is_revision_bound_and_namespaced() -> None:
    state = _State()
    application = ReportingLifecycleToolApplication(
        mutation=ReportingStateMutationApplication(
            kernel=_SharedKernelExtensionStateApplication(state)
        ),
        state=state,
        contexts=_Contexts(),
        clock=_Clock(),
    )
    draft = _invoke(
        application,
        "report_draft.update",
        {
            "task_id": "task-1",
            "title": "Final report",
            "summary": "Bounded metadata.",
            "content_ref": _content_ref().to_dict(),
            "idempotency_key": "draft-1",
        },
    )
    observed = _invoke(application, "report_draft.get", {"task_id": "task-1"})
    published = _invoke(
        application,
        "report.publish",
        {
            "report_id": "report-target-1",
            "task_id": "task-1",
            "report_contract_id": "enzymedesign.aox.report@1",
            "report_version": 1,
            "report_format": "markdown",
            "title": "Final report",
            "summary": "Bounded metadata.",
            "content_ref": _content_ref().to_dict(),
            "idempotency_key": "publish-1",
        },
    )
    render = _invoke(
        application,
        "report.render.request",
        {
            "report_id": "report-target-1",
            "report_digest": published["report_digest"],
            "renderer_id": "openzyme.reporting.renderer@1",
            "renderer_contract_digest": ZERO_DIGEST,
            "output_format": "pdf",
            "idempotency_key": "render-1",
        },
    )

    assert draft["content_ref"]["path"] == "reports/final.md"
    assert observed["entity_id"] == draft["entity_id"]
    assert published["state"] == "published"
    assert published["report_version"] == 1
    assert render["state"] == "requested"
    assert render["report_id"] == "report-target-1"
    assert all("body" not in record.payload for record in state.records.values())


def test_target_reporting_application_rejects_cross_session_context() -> None:
    state = _State()
    application = ReportingLifecycleToolApplication(
        mutation=ReportingStateMutationApplication(
            kernel=_SharedKernelExtensionStateApplication(state)
        ),
        state=state,
        contexts=_Contexts(session_id="session-other"),
        clock=_Clock(),
    )

    with pytest.raises(ValueError, match="crossed its Session"):
        _invoke(
            application,
            "report_draft.update",
            {
                "task_id": "task-1",
                "title": "Final report",
                "summary": "Bounded metadata.",
                "idempotency_key": "draft-cross-session",
            },
        )
    assert state.records == {}


def test_reporting_projection_and_renderer_are_extension_owned_and_bounded() -> None:
    state = _State()
    record = ExtensionStateRecord(
        namespace=REPORTING_STATE_NAMESPACE,
        entity_kind="draft",
        entity_id="draft-1",
        state_version=1,
        payload={
            "session_id": "session-1",
            "draft_id": "draft-1",
            "task_id": "task-1",
            "owner_agent_member_id": "agent-1",
            "state": "draft",
            "title": "Report",
            "summary": "Metadata",
            "content_ref": None,
            "updated_at": "2026-08-21T00:00:00+00:00",
        },
        record_digest=ZERO_DIGEST,
    )
    state.records[(record.entity_kind, record.entity_id)] = record
    payload, cursor = ReportingExtensionStateProjectionApplication(state).project(
        session_id="session-1",
        actor_id="agent-1",
        max_items=20,
        cursor=None,
    )
    rendered = ReportingUiRenderer().render(payload)

    assert cursor is None
    assert rendered["drafts_count"] == 1
    assert rendered["reports_count"] == 0
    assert rendered["task_finished"] is False
    assert "body" not in str(rendered)
