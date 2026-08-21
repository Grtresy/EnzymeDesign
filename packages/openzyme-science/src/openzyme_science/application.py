from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import ToolInvocation
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import ExtensionStateRecord
from openzyme_extension_spi import KernelCommandContext

from .transaction import SCIENCE_STATE_NAMESPACE
from .transaction import ScienceStateMutationApplication


class ScienceInvocationContextResolver(Protocol):
    """Resolve the exact Kernel authority/bundle context for one tool call."""

    def resolve(
        self,
        *,
        invocation: ToolInvocation,
        idempotency_key: str,
    ) -> KernelCommandContext: ...


class ScienceStateQuery(Protocol):
    """Read one authorized Science record without exposing a repository handle."""

    def get_session_record(
        self,
        *,
        namespace: str,
        session_id: str,
        entity_kind: str,
        entity_id: str,
    ) -> ExtensionStateRecord | None: ...


def _required_string(
    arguments: Mapping[str, JsonValue],
    field_name: str,
) -> str:
    value = arguments.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _stable_entity_id(prefix: str, payload: Mapping[str, JsonValue]) -> str:
    digest = canonical_sha256_digest(payload).removeprefix("sha256:")
    return f"{prefix}_{digest[:24]}"


@dataclass(slots=True)
class ScienceLifecycleToolApplication:
    """Translate typed Science tools into Kernel-admitted namespace mutations.

    This application receives no Core repository aggregate, SQLite connection, Host
    service or external-effect implementation.  Reads use a bounded Science query and
    every write is re-admitted by Kernel through ``ScienceStateMutationApplication``.
    """

    mutation: ScienceStateMutationApplication
    state: ScienceStateQuery
    contexts: ScienceInvocationContextResolver

    def invoke(self, *, invocation: ToolInvocation) -> Mapping[str, JsonValue]:
        arguments = invocation.arguments
        tool_name = invocation.tool_name
        if tool_name == "scientific.attempt.inspect":
            return self._inspect(invocation)
        idempotency_key = _required_string(arguments, "idempotency_key")
        context = self.contexts.resolve(
            invocation=invocation,
            idempotency_key=idempotency_key,
        )
        if context.session_id != invocation.session_id:
            raise ValueError("Science command context crossed its Session")
        if context.actor_id != invocation.agent_member_id:
            raise ValueError("Science command context crossed its Agent member")
        if tool_name == "scientific.selection.begin":
            return self._begin_selection(invocation, context)
        if tool_name == "scientific.operation.disposition":
            return self._record_disposition(invocation, context)
        if tool_name == "scientific.operation.adopt":
            return self._record_adoption(invocation, context)
        if tool_name == "scientific.selection.seal":
            return self._seal_selection(invocation, context)
        if tool_name == "scientific.attempt.close":
            return self._close_attempt(invocation, context)
        raise ValueError("Science tool identity is not declared")

    def _get(
        self,
        *,
        invocation: ToolInvocation,
        entity_kind: str,
        entity_id: str,
    ) -> ExtensionStateRecord:
        record = self.state.get_session_record(
            namespace=SCIENCE_STATE_NAMESPACE,
            session_id=invocation.session_id,
            entity_kind=entity_kind,
            entity_id=entity_id,
        )
        if record is None:
            raise ValueError(f"Science {entity_kind} record was not found")
        if (
            record.namespace != SCIENCE_STATE_NAMESPACE
            or record.entity_kind != entity_kind
            or record.entity_id != entity_id
            or record.payload.get("session_id") != invocation.session_id
        ):
            raise ValueError("Science query crossed its exact identity")
        return record

    def _attempt_identity(
        self,
        *,
        invocation: ToolInvocation,
        attempt_id: str,
    ) -> tuple[ExtensionStateRecord, int]:
        attempt = self._get(
            invocation=invocation,
            entity_kind="attempt",
            entity_id=attempt_id,
        )
        generation = attempt.payload.get("attempt_generation")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ValueError("Science attempt generation is invalid")
        if attempt.payload.get("attempt_id") != attempt_id:
            raise ValueError("Science attempt identity drifted")
        if attempt.payload.get("state") in {"closed", "failed", "retired"}:
            raise ValueError("Science attempt no longer accepts mutation")
        return attempt, generation

    def _selection_identity(
        self,
        *,
        invocation: ToolInvocation,
        selection_id: str,
    ) -> tuple[ExtensionStateRecord, str, int]:
        selection = self._get(
            invocation=invocation,
            entity_kind="selection",
            entity_id=selection_id,
        )
        attempt_id = selection.payload.get("attempt_id")
        generation = selection.payload.get("attempt_generation")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("Science selection has no exact attempt")
        _, current_generation = self._attempt_identity(
            invocation=invocation,
            attempt_id=attempt_id,
        )
        if generation != current_generation:
            raise ValueError("Science selection crossed its attempt generation")
        return selection, attempt_id, current_generation

    def _inspect(self, invocation: ToolInvocation) -> Mapping[str, JsonValue]:
        arguments = invocation.arguments
        attempt_id = arguments.get("attempt_id")
        selection_id = arguments.get("selection_id")
        if (attempt_id is None) == (selection_id is None):
            raise ValueError("Science inspect requires exactly one record identity")
        if isinstance(attempt_id, str):
            record = self._get(
                invocation=invocation,
                entity_kind="attempt",
                entity_id=attempt_id,
            )
        elif isinstance(selection_id, str):
            record = self._get(
                invocation=invocation,
                entity_kind="selection",
                entity_id=selection_id,
            )
        else:
            raise ValueError("Science inspect identity is invalid")
        return {
            "state": str(record.payload.get("state", "observed")),
            "entity_kind": record.entity_kind,
            "entity_id": record.entity_id,
            "state_version": record.state_version,
            "record_digest": record.record_digest,
        }

    def _begin_selection(
        self,
        invocation: ToolInvocation,
        context: KernelCommandContext,
    ) -> Mapping[str, JsonValue]:
        attempt_id = _required_string(invocation.arguments, "attempt_id")
        _, generation = self._attempt_identity(
            invocation=invocation,
            attempt_id=attempt_id,
        )
        parent_id = invocation.arguments.get("parent_selection_id")
        expected_parent_version = invocation.arguments.get(
            "expected_head_state_version"
        )
        if parent_id is not None:
            if not isinstance(parent_id, str) or not parent_id:
                raise ValueError("parent_selection_id is invalid")
            parent, parent_attempt_id, parent_generation = self._selection_identity(
                invocation=invocation,
                selection_id=parent_id,
            )
            if parent_attempt_id != attempt_id or parent_generation != generation:
                raise ValueError("Science parent selection crossed its attempt")
            if expected_parent_version != parent.state_version:
                raise ValueError("Science parent selection state version is stale")
        elif expected_parent_version is not None:
            raise ValueError("Science head version requires an exact parent selection")
        selection_id = _stable_entity_id(
            "selection",
            {
                "session_id": invocation.session_id,
                "attempt_id": attempt_id,
                "attempt_generation": generation,
                "parent_selection_id": parent_id,
                "idempotency_key": context.idempotency_key,
            },
        )
        result = self.mutation.upsert_record(
            context=context,
            entity_kind="selection",
            entity_id=selection_id,
            expected_state_version=None,
            record={
                "session_id": invocation.session_id,
                "selection_id": selection_id,
                "attempt_id": attempt_id,
                "attempt_generation": generation,
                "parent_selection_id": parent_id,
                "state": "open",
                "actor_id": context.actor_id,
                "idempotency_key": context.idempotency_key,
            },
        )
        return {"state": "open", **dict(result.result)}

    def _record_disposition(
        self,
        invocation: ToolInvocation,
        context: KernelCommandContext,
    ) -> Mapping[str, JsonValue]:
        selection_id = _required_string(invocation.arguments, "selection_id")
        operation_id = _required_string(invocation.arguments, "operation_id")
        selection, attempt_id, generation = self._selection_identity(
            invocation=invocation,
            selection_id=selection_id,
        )
        if selection.payload.get("state") != "open":
            raise ValueError("Science selection no longer accepts dispositions")
        kind = _required_string(invocation.arguments, "kind")
        disposition_id = _stable_entity_id(
            "disposition",
            {
                "session_id": invocation.session_id,
                "selection_id": selection_id,
                "operation_id": operation_id,
                "kind": kind,
                "idempotency_key": context.idempotency_key,
            },
        )
        result = self.mutation.upsert_record(
            context=context,
            entity_kind="disposition",
            entity_id=disposition_id,
            expected_state_version=None,
            record={
                "session_id": invocation.session_id,
                "disposition_id": disposition_id,
                "attempt_id": attempt_id,
                "attempt_generation": generation,
                "selection_id": selection_id,
                "operation_id": operation_id,
                "kind": kind,
                "reason_code": _required_string(invocation.arguments, "reason_code"),
                "workflow_role": invocation.arguments.get("workflow_role"),
                "replacement_operation_id": invocation.arguments.get(
                    "replacement_operation_id"
                ),
                "state": "recorded",
                "actor_id": context.actor_id,
                "idempotency_key": context.idempotency_key,
            },
        )
        return {"state": "recorded", **dict(result.result)}

    def _record_adoption(
        self,
        invocation: ToolInvocation,
        context: KernelCommandContext,
    ) -> Mapping[str, JsonValue]:
        selection_id = _required_string(invocation.arguments, "selection_id")
        operation_id = _required_string(invocation.arguments, "operation_id")
        selection, attempt_id, generation = self._selection_identity(
            invocation=invocation,
            selection_id=selection_id,
        )
        if selection.payload.get("state") != "open":
            raise ValueError("Science selection no longer accepts adoptions")
        workflow_role = _required_string(invocation.arguments, "workflow_role")
        adoption_id = _stable_entity_id(
            "adoption",
            {
                "session_id": invocation.session_id,
                "selection_id": selection_id,
                "operation_id": operation_id,
                "workflow_role": workflow_role,
                "idempotency_key": context.idempotency_key,
            },
        )
        result = self.mutation.upsert_record(
            context=context,
            entity_kind="effect_adoption",
            entity_id=adoption_id,
            expected_state_version=None,
            record={
                "session_id": invocation.session_id,
                "adoption_id": adoption_id,
                "attempt_id": attempt_id,
                "attempt_generation": generation,
                "selection_id": selection_id,
                "operation_id": operation_id,
                "workflow_role": workflow_role,
                "reason_code": _required_string(invocation.arguments, "reason_code"),
                "state": "adopted",
                "actor_id": context.actor_id,
                "idempotency_key": context.idempotency_key,
            },
        )
        return {"state": "adopted", **dict(result.result)}

    def _seal_selection(
        self,
        invocation: ToolInvocation,
        context: KernelCommandContext,
    ) -> Mapping[str, JsonValue]:
        selection_id = _required_string(invocation.arguments, "selection_id")
        selection, _, _ = self._selection_identity(
            invocation=invocation,
            selection_id=selection_id,
        )
        if selection.payload.get("state") != "open":
            raise ValueError("Science selection is not open")
        record = dict(selection.payload)
        record.update(
            {
                "state": "sealed",
                "operation_universe_digest": _required_string(
                    invocation.arguments,
                    "expected_universe_digest",
                ),
                "sealed_by_actor_id": context.actor_id,
                "seal_idempotency_key": context.idempotency_key,
            }
        )
        result = self.mutation.upsert_record(
            context=context,
            entity_kind="selection",
            entity_id=selection_id,
            expected_state_version=selection.state_version,
            record=record,
        )
        return {"state": "sealed", **dict(result.result)}

    def _close_attempt(
        self,
        invocation: ToolInvocation,
        context: KernelCommandContext,
    ) -> Mapping[str, JsonValue]:
        attempt_id = _required_string(invocation.arguments, "attempt_id")
        selection_id = _required_string(invocation.arguments, "selection_id")
        _, generation = self._attempt_identity(
            invocation=invocation,
            attempt_id=attempt_id,
        )
        selection, selection_attempt_id, selection_generation = (
            self._selection_identity(
                invocation=invocation,
                selection_id=selection_id,
            )
        )
        if (
            selection_attempt_id != attempt_id
            or selection_generation != generation
            or selection.payload.get("state") != "sealed"
        ):
            raise ValueError("Science closure selection is not the exact sealed attempt")
        closure_id = _stable_entity_id(
            "closure",
            {
                "session_id": invocation.session_id,
                "attempt_id": attempt_id,
                "attempt_generation": generation,
                "selection_id": selection_id,
                "idempotency_key": context.idempotency_key,
            },
        )
        result = self.mutation.upsert_record(
            context=context,
            entity_kind="attempt_closure",
            entity_id=closure_id,
            expected_state_version=None,
            record={
                "session_id": invocation.session_id,
                "closure_id": closure_id,
                "attempt_id": attempt_id,
                "attempt_generation": generation,
                "selection_id": selection_id,
                "state": "closed",
                "actor_id": context.actor_id,
                "idempotency_key": context.idempotency_key,
                "task_finished": False,
            },
        )
        return {"state": "closed", **dict(result.result)}


__all__ = [
    "ScienceInvocationContextResolver",
    "ScienceLifecycleToolApplication",
    "ScienceStateQuery",
]
