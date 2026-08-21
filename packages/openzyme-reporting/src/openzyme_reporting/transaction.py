from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from openzyme_contracts import RevisionPathEntryKind
from openzyme_contracts import RevisionPathRef
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import ExtensionMutationPlan
from openzyme_extension_spi import ExtensionMutationResult
from openzyme_extension_spi import ExtensionStateApplicationService
from openzyme_extension_spi import ExtensionStateCommand
from openzyme_extension_spi import ExtensionStateMutation
from openzyme_extension_spi import ExtensionStateMutationKind
from openzyme_extension_spi import ExtensionStateReader
from openzyme_extension_spi import ExtensionStateWriter
from openzyme_extension_spi import ExtensionTransactionBudget

from .lifecycle import ReportRenderReceipt
from .lifecycle import ReportValidationReceipt
from .lifecycle import ReportVersion


REPORTING_PLUGIN_ID = "openzyme.reporting"
REPORTING_STATE_NAMESPACE = "openzyme_reporting"
REPORTING_TRANSACTION_PARTICIPANT_ID = "openzyme.reporting.transaction@1"

_ENTITY_KINDS = frozenset(
    {
        "draft",
        "report_version",
        "render_receipt",
        "validation_receipt",
    }
)
_FORBIDDEN_BODY_FIELDS = frozenset(
    {
        "body",
        "bytes",
        "content",
        "markdown",
        "html",
        "pdf",
        "host_path",
        "private_path",
        "storage_uri",
    }
)


def _reject_embedded_body(value: object, *, path: str = "record") -> None:
    if isinstance(value, Mapping):
        forbidden = _FORBIDDEN_BODY_FIELDS.intersection(str(key) for key in value)
        if forbidden:
            raise ValueError(
                f"{path} contains forbidden report body/storage fields: "
                + ", ".join(sorted(forbidden))
            )
        for key, item in value.items():
            _reject_embedded_body(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_embedded_body(item, path=f"{path}[{index}]")


class ReportingTransactionParticipant:
    """Namespace-confined report state writer; it cannot render or publish files."""

    participant_id = REPORTING_TRANSACTION_PARTICIPANT_ID
    state_namespace = REPORTING_STATE_NAMESPACE

    def prepare(
        self,
        command: ExtensionStateCommand,
        state: ExtensionStateReader,
    ) -> ExtensionMutationPlan:
        if (
            command.participant_id != self.participant_id
            or command.namespace != self.state_namespace
            or command.context.owner_plugin_id != REPORTING_PLUGIN_ID
            or command.operation != "upsert_reporting_records"
        ):
            raise ValueError("Reporting command crossed its exact participant")
        if set(command.payload) != {"records"}:
            raise ValueError("Reporting transaction payload fields are closed")
        raw_records = command.payload["records"]
        if not isinstance(raw_records, (list, tuple)) or not 1 <= len(raw_records) <= 2:
            raise ValueError("Reporting transaction accepts one or two records")

        mutations: list[ExtensionStateMutation] = []
        for raw in raw_records:
            if not isinstance(raw, Mapping) or set(raw) != {
                "entity_kind",
                "entity_id",
                "expected_state_version",
                "record",
            }:
                raise ValueError("Reporting record mutation fields are closed")
            entity_kind = raw["entity_kind"]
            entity_id = raw["entity_id"]
            expected = raw["expected_state_version"]
            record = raw["record"]
            if entity_kind not in _ENTITY_KINDS:
                raise ValueError("Reporting entity kind is not declared")
            if not isinstance(entity_id, str) or not entity_id:
                raise ValueError("Reporting entity_id must be non-empty")
            if expected is not None and (
                not isinstance(expected, int)
                or isinstance(expected, bool)
                or expected < 1
            ):
                raise ValueError("expected_state_version must be positive or null")
            if not isinstance(record, Mapping):
                raise ValueError("Reporting record must be a JSON object")
            _reject_embedded_body(record)
            if record.get("session_id") != command.context.session_id:
                raise ValueError("Reporting record crossed its Session")
            if entity_kind == "report_version":
                parsed = ReportVersion.from_dict(dict(record))
                if parsed.report_id != entity_id:
                    raise ValueError("report entity identity drifted")
            elif entity_kind == "render_receipt":
                parsed_render = ReportRenderReceipt.from_dict(dict(record))
                if parsed_render.render_id != entity_id:
                    raise ValueError("render receipt identity drifted")
                report = state.get(
                    namespace=self.state_namespace,
                    entity_kind="report_version",
                    entity_id=parsed_render.report_id,
                )
                if (
                    report is None
                    or report.payload.get("session_id") != command.context.session_id
                    or report.payload.get("report_digest")
                    != parsed_render.source_report_digest
                ):
                    raise ValueError("render receipt source report identity drifted")
            elif entity_kind == "validation_receipt":
                parsed_validation = ReportValidationReceipt.from_dict(dict(record))
                if parsed_validation.validation_id != entity_id:
                    raise ValueError("validation receipt identity drifted")
                report = state.get(
                    namespace=self.state_namespace,
                    entity_kind="report_version",
                    entity_id=parsed_validation.report_id,
                )
                if (
                    report is None
                    or report.payload.get("session_id") != command.context.session_id
                    or report.payload.get("task_id") != parsed_validation.task_id
                    or report.payload.get("report_version")
                    != parsed_validation.report_version
                    or report.payload.get("report_digest")
                    != parsed_validation.report_digest
                ):
                    raise ValueError("validation receipt source report identity drifted")
            else:
                expected_draft_fields = {
                    "session_id",
                    "draft_id",
                    "task_id",
                    "owner_agent_member_id",
                    "state",
                    "title",
                    "summary",
                    "content_ref",
                    "updated_at",
                }
                if set(record) != expected_draft_fields:
                    raise ValueError("Reporting draft fields are closed")
                if record.get("draft_id") != entity_id:
                    raise ValueError("Reporting draft identity drifted")
                for field_name in (
                    "task_id",
                    "owner_agent_member_id",
                    "title",
                    "updated_at",
                ):
                    if not isinstance(record.get(field_name), str) or not record.get(
                        field_name
                    ):
                        raise ValueError(f"Reporting draft {field_name} is invalid")
                title = str(record["title"])
                summary = record["summary"]
                if len(title.encode("utf-8")) > 1_024:
                    raise ValueError("Reporting draft title exceeds its budget")
                if not isinstance(summary, str) or len(summary.encode("utf-8")) > 16_384:
                    raise ValueError("Reporting draft summary exceeds its budget")
                content_ref = record["content_ref"]
                if content_ref is not None:
                    parsed_ref = RevisionPathRef.from_dict(dict(content_ref))
                    if (
                        parsed_ref.session_id != command.context.session_id
                        or parsed_ref.entry_kind
                        not in {
                            RevisionPathEntryKind.FILE,
                            RevisionPathEntryKind.LFS_FILE,
                        }
                    ):
                        raise ValueError(
                            "Reporting draft content is not an immutable Session file"
                        )
            current = state.get(
                namespace=self.state_namespace,
                entity_kind=str(entity_kind),
                entity_id=entity_id,
            )
            if current is not None and expected is None:
                raise ValueError("Reporting record already exists")
            mutations.append(
                ExtensionStateMutation(
                    mutation_kind=ExtensionStateMutationKind.UPSERT,
                    namespace=self.state_namespace,
                    entity_kind=str(entity_kind),
                    entity_id=entity_id,
                    expected_state_version=expected,
                    payload=dict(record),
                )
            )

        return ExtensionMutationPlan.create(
            plan_id=f"reporting-plan-{command.context.command_id}",
            participant_id=self.participant_id,
            namespace=self.state_namespace,
            command_id=command.context.command_id,
            mutations=tuple(mutations),
            budget=ExtensionTransactionBudget(
                max_reads=4,
                max_mutations=2,
                max_payload_bytes=524_288,
                max_duration_ms=1_000,
            ),
        )

    def apply(
        self,
        plan: ExtensionMutationPlan,
        state: ExtensionStateWriter,
    ) -> ExtensionMutationResult:
        if (
            plan.participant_id != self.participant_id
            or plan.namespace != self.state_namespace
            or not 1 <= len(plan.mutations) <= 2
        ):
            raise ValueError("Reporting plan crossed its exact participant")
        changed = tuple(state.upsert(mutation) for mutation in plan.mutations)
        result: dict[str, JsonValue] = {
            "entity_ids": [record.entity_id for record in changed],
            "state_versions": [record.state_version for record in changed],
            "workspace_publication_performed": False,
            "render_performed": False,
            "fallback_performed": False,
            "task_finished": False,
        }
        return ExtensionMutationResult.create(
            plan_id=plan.plan_id,
            participant_id=self.participant_id,
            namespace=self.state_namespace,
            mutation_applied=True,
            changed_records=changed,
            result=result,
        )


@dataclass(slots=True)
class ReportingStateMutationApplication:
    """Reporting-facing gateway to the Kernel-admitted restricted participant."""

    kernel: ExtensionStateApplicationService

    def upsert_records(
        self,
        *,
        context: object,
        records: tuple[Mapping[str, JsonValue], ...],
    ) -> ExtensionMutationResult:
        from openzyme_extension_spi import KernelCommandContext

        if not isinstance(context, KernelCommandContext):
            raise TypeError("Reporting mutation requires an exact KernelCommandContext")
        if context.owner_plugin_id != REPORTING_PLUGIN_ID:
            raise ValueError("Reporting mutation context belongs to another Plugin")
        if not 1 <= len(records) <= 2:
            raise ValueError("Reporting mutation requires one or two records")
        return self.kernel.execute(
            ExtensionStateCommand(
                context=context,
                participant_id=REPORTING_TRANSACTION_PARTICIPANT_ID,
                namespace=REPORTING_STATE_NAMESPACE,
                operation="upsert_reporting_records",
                payload={"records": [dict(record) for record in records]},
            )
        )


__all__ = [
    "REPORTING_PLUGIN_ID",
    "REPORTING_STATE_NAMESPACE",
    "REPORTING_TRANSACTION_PARTICIPANT_ID",
    "ReportingStateMutationApplication",
    "ReportingTransactionParticipant",
]
