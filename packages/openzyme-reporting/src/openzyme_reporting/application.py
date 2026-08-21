from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import RevisionPathEntryKind
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import ToolInvocation
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import ExtensionStateRecord
from openzyme_extension_spi import KernelCommandContext

from .lifecycle import ReportFormat
from .lifecycle import ReportRenderReceipt
from .lifecycle import ReportRenderStatus
from .lifecycle import ReportVersion
from .transaction import REPORTING_STATE_NAMESPACE
from .transaction import ReportingStateMutationApplication


class ReportingInvocationContextResolver(Protocol):
    """Resolve one exact Kernel authority/bundle context for a mutation."""

    def resolve(
        self,
        *,
        invocation: ToolInvocation,
        idempotency_key: str,
    ) -> KernelCommandContext: ...


class ReportingStateQuery(Protocol):
    """Bounded Reporting state query without repository or SQLite access."""

    def get_session_record(
        self,
        *,
        namespace: str,
        session_id: str,
        entity_kind: str,
        entity_id: str,
    ) -> ExtensionStateRecord | None: ...

    def list_session_records(
        self,
        *,
        namespace: str,
        session_id: str,
        entity_kinds: tuple[str, ...],
        after_cursor: str | None,
        limit: int,
    ) -> tuple[tuple[ExtensionStateRecord, ...], str | None]: ...


class ReportingClock(Protocol):
    def now(self) -> str: ...


def _required_string(arguments: Mapping[str, JsonValue], field_name: str) -> str:
    value = arguments.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _stable_entity_id(prefix: str, payload: Mapping[str, JsonValue]) -> str:
    digest = canonical_sha256_digest(payload).removeprefix("sha256:")
    return f"{prefix}_{digest[:24]}"


def _content_ref(value: JsonValue, *, session_id: str) -> RevisionPathRef:
    if not isinstance(value, Mapping):
        raise ValueError("content_ref must be an exact RevisionPathRef")
    ref = RevisionPathRef.from_dict(dict(value))
    if ref.session_id != session_id:
        raise ValueError("report content reference crossed its Session")
    if ref.entry_kind not in {
        RevisionPathEntryKind.FILE,
        RevisionPathEntryKind.LFS_FILE,
    }:
        raise ValueError("report content must reference one immutable file")
    return ref


@dataclass(slots=True)
class ReportingLifecycleToolApplication:
    """Translate Reporting tools into restricted namespaced state mutations."""

    mutation: ReportingStateMutationApplication
    state: ReportingStateQuery
    contexts: ReportingInvocationContextResolver
    clock: ReportingClock

    def invoke(self, *, invocation: ToolInvocation) -> Mapping[str, JsonValue]:
        if invocation.tool_name == "report_draft.get":
            return self._get_draft(invocation)
        idempotency_key = _required_string(
            invocation.arguments,
            "idempotency_key",
        )
        context = self.contexts.resolve(
            invocation=invocation,
            idempotency_key=idempotency_key,
        )
        if context.session_id != invocation.session_id:
            raise ValueError("Reporting command context crossed its Session")
        if context.actor_id != invocation.agent_member_id:
            raise ValueError("Reporting command context crossed its Agent member")
        if invocation.tool_name == "report_draft.update":
            return self._update_draft(invocation, context)
        if invocation.tool_name == "report.publish":
            return self._publish_report(invocation, context)
        if invocation.tool_name == "report.render.request":
            return self._request_render(invocation, context)
        raise ValueError("Reporting tool identity is not declared")

    def _get_record(
        self,
        *,
        invocation: ToolInvocation,
        entity_kind: str,
        entity_id: str,
    ) -> ExtensionStateRecord:
        record = self.state.get_session_record(
            namespace=REPORTING_STATE_NAMESPACE,
            session_id=invocation.session_id,
            entity_kind=entity_kind,
            entity_id=entity_id,
        )
        if record is None:
            raise ValueError(f"Reporting {entity_kind} record was not found")
        if (
            record.namespace != REPORTING_STATE_NAMESPACE
            or record.entity_kind != entity_kind
            or record.entity_id != entity_id
            or record.payload.get("session_id") != invocation.session_id
        ):
            raise ValueError("Reporting query crossed its exact identity")
        return record

    def _records(
        self,
        *,
        invocation: ToolInvocation,
        entity_kind: str,
    ) -> tuple[ExtensionStateRecord, ...]:
        records, next_cursor = self.state.list_session_records(
            namespace=REPORTING_STATE_NAMESPACE,
            session_id=invocation.session_id,
            entity_kinds=(entity_kind,),
            after_cursor=None,
            limit=200,
        )
        if next_cursor is not None:
            raise ValueError("Reporting state exceeds the bounded decision window")
        if any(
            record.namespace != REPORTING_STATE_NAMESPACE
            or record.entity_kind != entity_kind
            or record.payload.get("session_id") != invocation.session_id
            for record in records
        ):
            raise ValueError("Reporting query crossed its exact identity")
        return records

    @staticmethod
    def _result(record: ExtensionStateRecord) -> Mapping[str, JsonValue]:
        payload = record.payload
        result: dict[str, JsonValue] = {
            "state": str(payload.get("state", payload.get("status", "observed"))),
            "entity_kind": record.entity_kind,
            "entity_id": record.entity_id,
            "state_version": record.state_version,
            "record_digest": record.record_digest,
        }
        for field_name in (
            "task_id",
            "title",
            "summary",
            "content_ref",
            "report_id",
            "report_version",
            "report_digest",
            "render_id",
            "receipt_digest",
        ):
            if field_name in payload:
                result[field_name] = payload[field_name]
        return result

    def _get_draft(self, invocation: ToolInvocation) -> Mapping[str, JsonValue]:
        draft_id = invocation.arguments.get("draft_id")
        task_id = invocation.arguments.get("task_id")
        if (draft_id is None) == (task_id is None):
            raise ValueError("report_draft.get requires exactly one identity")
        if isinstance(draft_id, str) and draft_id:
            return self._result(
                self._get_record(
                    invocation=invocation,
                    entity_kind="draft",
                    entity_id=draft_id,
                )
            )
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id must be a non-empty string")
        matches = tuple(
            record
            for record in self._records(invocation=invocation, entity_kind="draft")
            if record.payload.get("task_id") == task_id
        )
        if len(matches) != 1:
            raise ValueError("Reporting draft by Task is missing or ambiguous")
        return self._result(matches[0])

    def _update_draft(
        self,
        invocation: ToolInvocation,
        context: KernelCommandContext,
    ) -> Mapping[str, JsonValue]:
        task_id = _required_string(invocation.arguments, "task_id")
        if invocation.task_id is not None and invocation.task_id != task_id:
            raise ValueError("Reporting draft crossed its invocation Task")
        draft_id_value = invocation.arguments.get("draft_id")
        draft_id = (
            str(draft_id_value)
            if isinstance(draft_id_value, str) and draft_id_value
            else _stable_entity_id(
                "report_draft",
                {"session_id": invocation.session_id, "task_id": task_id},
            )
        )
        existing = self.state.get_session_record(
            namespace=REPORTING_STATE_NAMESPACE,
            session_id=invocation.session_id,
            entity_kind="draft",
            entity_id=draft_id,
        )
        expected = invocation.arguments.get("expected_state_version")
        if existing is None and expected is not None:
            raise ValueError("Reporting draft expected version has no existing record")
        if existing is not None and expected != existing.state_version:
            raise ValueError("Reporting draft state version is stale")
        raw_ref = invocation.arguments.get("content_ref")
        content_ref = (
            None
            if raw_ref is None
            else _content_ref(raw_ref, session_id=invocation.session_id).to_dict()
        )
        record: dict[str, JsonValue] = {
            "session_id": invocation.session_id,
            "draft_id": draft_id,
            "task_id": task_id,
            "owner_agent_member_id": context.actor_id,
            "state": "draft",
            "title": _required_string(invocation.arguments, "title"),
            "summary": str(invocation.arguments.get("summary", "")),
            "content_ref": content_ref,
            "updated_at": self.clock.now(),
        }
        result = self.mutation.upsert_records(
            context=context,
            records=(
                {
                    "entity_kind": "draft",
                    "entity_id": draft_id,
                    "expected_state_version": expected,
                    "record": record,
                },
            ),
        )
        changed = result.changed_records[0]
        return self._result(changed)

    def _publish_report(
        self,
        invocation: ToolInvocation,
        context: KernelCommandContext,
    ) -> Mapping[str, JsonValue]:
        arguments = invocation.arguments
        task_id = _required_string(arguments, "task_id")
        if invocation.task_id is not None and invocation.task_id != task_id:
            raise ValueError("Reporting report crossed its invocation Task")
        report_id = _required_string(arguments, "report_id")
        if self.state.get_session_record(
            namespace=REPORTING_STATE_NAMESPACE,
            session_id=invocation.session_id,
            entity_kind="report_version",
            entity_id=report_id,
        ) is not None:
            raise ValueError("Reporting report identity already exists")
        content_ref = _content_ref(
            arguments.get("content_ref"),
            session_id=invocation.session_id,
        )
        version = arguments.get("report_version")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError("report_version must be an integer")
        predecessor_id = arguments.get("supersedes_report_id")
        reports = self._records(invocation=invocation, entity_kind="report_version")
        related = tuple(
            ReportVersion.from_dict(dict(record.payload))
            for record in reports
            if record.payload.get("task_id") == task_id
            and record.payload.get("report_contract_id")
            == arguments.get("report_contract_id")
        )
        if version == 1:
            if related:
                raise ValueError("Reporting first version already exists")
        else:
            if not isinstance(predecessor_id, str) or not predecessor_id:
                raise ValueError("Reporting correction requires an exact predecessor")
            predecessor = next(
                (item for item in related if item.report_id == predecessor_id),
                None,
            )
            if (
                predecessor is None
                or predecessor.report_version != version - 1
                or max(item.report_version for item in related) != predecessor.report_version
            ):
                raise ValueError("Reporting predecessor is not the exact latest version")
        report = ReportVersion.create(
            report_id=report_id,
            project_id=content_ref.project_id,
            session_id=invocation.session_id,
            task_id=task_id,
            owner_agent_member_id=context.actor_id,
            report_contract_id=_required_string(arguments, "report_contract_id"),
            report_version=version,
            report_format=ReportFormat(_required_string(arguments, "report_format")),
            title=_required_string(arguments, "title"),
            summary=str(arguments.get("summary", "")),
            content_ref=content_ref,
            supersedes_report_id=(
                None if predecessor_id is None else str(predecessor_id)
            ),
            created_at=self.clock.now(),
        )
        result = self.mutation.upsert_records(
            context=context,
            records=(
                {
                    "entity_kind": "report_version",
                    "entity_id": report.report_id,
                    "expected_state_version": None,
                    "record": report.to_dict(),
                },
            ),
        )
        return {**self._result(result.changed_records[0]), "state": "published"}

    def _request_render(
        self,
        invocation: ToolInvocation,
        context: KernelCommandContext,
    ) -> Mapping[str, JsonValue]:
        arguments = invocation.arguments
        report_id = _required_string(arguments, "report_id")
        source = self._get_record(
            invocation=invocation,
            entity_kind="report_version",
            entity_id=report_id,
        )
        report = ReportVersion.from_dict(dict(source.payload))
        report_digest = _required_string(arguments, "report_digest")
        if report.report_digest != report_digest:
            raise ValueError("Reporting render source digest drifted")
        render_id = _stable_entity_id(
            "report_render",
            {
                "session_id": invocation.session_id,
                "report_id": report_id,
                "report_digest": report_digest,
                "renderer_id": arguments.get("renderer_id"),
                "output_format": arguments.get("output_format"),
                "idempotency_key": context.idempotency_key,
            },
        )
        receipt = ReportRenderReceipt.create(
            render_id=render_id,
            report_id=report_id,
            session_id=invocation.session_id,
            source_report_digest=report_digest,
            renderer_id=_required_string(arguments, "renderer_id"),
            renderer_contract_digest=_required_string(
                arguments,
                "renderer_contract_digest",
            ),
            status=ReportRenderStatus.REQUESTED,
            output_ref=None,
            failure_code=None,
            created_at=self.clock.now(),
        )
        result = self.mutation.upsert_records(
            context=context,
            records=(
                {
                    "entity_kind": "render_receipt",
                    "entity_id": render_id,
                    "expected_state_version": None,
                    "record": receipt.to_dict(),
                },
            ),
        )
        return {"state": "requested", **self._result(result.changed_records[0])}


__all__ = [
    "ReportingClock",
    "ReportingInvocationContextResolver",
    "ReportingLifecycleToolApplication",
    "ReportingStateQuery",
]
