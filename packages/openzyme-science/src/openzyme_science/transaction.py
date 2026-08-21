from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

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


SCIENCE_PLUGIN_ID = "openzyme.science"
SCIENCE_STATE_NAMESPACE = "openzyme_science"
SCIENCE_TRANSACTION_PARTICIPANT_ID = "openzyme.science.transaction@1"

_ENTITY_KINDS = frozenset(
    {
        "attempt",
        "attempt_authorization",
        "attempt_binding",
        "attempt_closure",
        "attempt_closure_request",
        "deliverable",
        "deliverable_bundle",
        "disposition",
        "effect_adoption",
        "selection",
        "validation_receipt",
    }
)
_FORBIDDEN_FIELDS = frozenset(
    {"arti" + "fact_id", "host_path", "remote_path", "storage_uri", "raw_log"}
)
_ATTEMPT_SCOPED_ENTITY_KINDS = frozenset(
    {
        "attempt_binding",
        "attempt_closure",
        "attempt_closure_request",
        "deliverable",
        "deliverable_bundle",
        "disposition",
        "effect_adoption",
        "selection",
        "validation_receipt",
    }
)


def _positive_integer(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _validate_science_identity(
    *,
    entity_kind: str,
    entity_id: str,
    record: Mapping[str, JsonValue],
    session_id: str,
    state: ExtensionStateReader,
) -> None:
    if record.get("session_id") != session_id:
        raise ValueError("Science record crossed its Session")
    if entity_kind == "attempt":
        if record.get("attempt_id") != entity_id:
            raise ValueError("Science attempt record crossed its attempt identity")
        _positive_integer(
            record.get("attempt_generation"),
            field_name="attempt_generation",
        )
        return
    if entity_kind not in _ATTEMPT_SCOPED_ENTITY_KINDS:
        return
    attempt_id = record.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise ValueError("Science record requires an exact attempt identity")
    attempt_generation = _positive_integer(
        record.get("attempt_generation"),
        field_name="attempt_generation",
    )
    attempt = state.get(
        namespace=SCIENCE_STATE_NAMESPACE,
        entity_kind="attempt",
        entity_id=attempt_id,
    )
    if attempt is None:
        raise ValueError("Science record references an unknown attempt")
    if attempt.payload.get("session_id") != session_id:
        raise ValueError("Science record crossed its Session")
    if attempt.payload.get("attempt_id") != attempt_id:
        raise ValueError("Science attempt record crossed its attempt identity")
    if attempt.payload.get("attempt_generation") != attempt_generation:
        raise ValueError("Science record crossed its attempt generation")
    identity_field = {
        "selection": "selection_id",
        "disposition": "disposition_id",
        "effect_adoption": "adoption_id",
        "deliverable": "deliverable_id",
        "deliverable_bundle": "bundle_id",
        "validation_receipt": "receipt_id",
        "attempt_closure_request": "closure_request_id",
        "attempt_closure": "closure_id",
    }.get(entity_kind)
    if identity_field is not None and record.get(identity_field) != entity_id:
        raise ValueError(f"Science {entity_kind} record crossed its entity identity")


class ScienceTransactionParticipant:
    """One bounded Science mutation enlisted in the Kernel-owned UoW."""

    participant_id = SCIENCE_TRANSACTION_PARTICIPANT_ID
    state_namespace = SCIENCE_STATE_NAMESPACE

    def prepare(
        self,
        command: ExtensionStateCommand,
        state: ExtensionStateReader,
    ) -> ExtensionMutationPlan:
        if (
            command.participant_id != self.participant_id
            or command.namespace != self.state_namespace
            or command.context.owner_plugin_id != SCIENCE_PLUGIN_ID
            or command.operation != "upsert_science_record"
            or set(command.payload)
            != {"entity_kind", "entity_id", "expected_state_version", "record"}
        ):
            raise ValueError("Science command crossed its exact participant")
        entity_kind = command.payload["entity_kind"]
        entity_id = command.payload["entity_id"]
        expected = command.payload["expected_state_version"]
        record = command.payload["record"]
        if entity_kind not in _ENTITY_KINDS:
            raise ValueError("Science entity kind is not declared")
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError("Science entity_id must be non-empty")
        if expected is not None and (
            not isinstance(expected, int) or isinstance(expected, bool) or expected < 1
        ):
            raise ValueError("expected_state_version must be positive or null")
        if not isinstance(record, Mapping):
            raise ValueError("Science record must be a JSON object")
        forbidden = _FORBIDDEN_FIELDS.intersection(str(key) for key in record)
        if forbidden:
            raise ValueError("Science record contains private or retired file-era fields")
        _validate_science_identity(
            entity_kind=str(entity_kind),
            entity_id=entity_id,
            record=record,
            session_id=command.context.session_id,
            state=state,
        )
        current = state.get(
            namespace=self.state_namespace,
            entity_kind=str(entity_kind),
            entity_id=entity_id,
        )
        if current is not None and expected is None:
            raise ValueError("Science record already exists")
        mutation = ExtensionStateMutation(
            mutation_kind=ExtensionStateMutationKind.UPSERT,
            namespace=self.state_namespace,
            entity_kind=str(entity_kind),
            entity_id=entity_id,
            expected_state_version=expected,
            payload=dict(record),
        )
        return ExtensionMutationPlan.create(
            plan_id=f"science-plan-{command.context.command_id}",
            participant_id=self.participant_id,
            namespace=self.state_namespace,
            command_id=command.context.command_id,
            mutations=(mutation,),
            budget=ExtensionTransactionBudget(
                max_reads=2,
                max_mutations=1,
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
            or len(plan.mutations) != 1
        ):
            raise ValueError("Science plan crossed its exact participant")
        record = state.upsert(plan.mutations[0])
        result: dict[str, JsonValue] = {
            "entity_kind": record.entity_kind,
            "entity_id": record.entity_id,
            "state_version": record.state_version,
            "fallback_performed": False,
            "task_finished": False,
        }
        return ExtensionMutationResult.create(
            plan_id=plan.plan_id,
            participant_id=self.participant_id,
            namespace=self.state_namespace,
            mutation_applied=True,
            changed_records=(record,),
            result=result,
        )


@dataclass(slots=True)
class ScienceStateMutationApplication:
    """Science-facing gateway to the Kernel-admitted restricted participant."""

    kernel: ExtensionStateApplicationService

    def upsert_record(
        self,
        *,
        context: object,
        entity_kind: str,
        entity_id: str,
        expected_state_version: int | None,
        record: Mapping[str, JsonValue],
    ) -> ExtensionMutationResult:
        from openzyme_extension_spi import KernelCommandContext

        if not isinstance(context, KernelCommandContext):
            raise TypeError("Science mutation requires an exact KernelCommandContext")
        if context.owner_plugin_id != SCIENCE_PLUGIN_ID:
            raise ValueError("Science mutation context belongs to another Plugin")
        return self.kernel.execute(
            ExtensionStateCommand(
                context=context,
                participant_id=SCIENCE_TRANSACTION_PARTICIPANT_ID,
                namespace=SCIENCE_STATE_NAMESPACE,
                operation="upsert_science_record",
                payload={
                    "entity_kind": entity_kind,
                    "entity_id": entity_id,
                    "expected_state_version": expected_state_version,
                    "record": dict(record),
                },
            )
        )


__all__ = [
    "SCIENCE_PLUGIN_ID",
    "SCIENCE_STATE_NAMESPACE",
    "SCIENCE_TRANSACTION_PARTICIPANT_ID",
    "ScienceStateMutationApplication",
    "ScienceTransactionParticipant",
]
