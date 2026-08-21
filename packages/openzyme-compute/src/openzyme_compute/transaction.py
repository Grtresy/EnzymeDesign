from __future__ import annotations

from collections.abc import Mapping

from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import ExtensionMutationPlan
from openzyme_extension_spi import ExtensionMutationResult
from openzyme_extension_spi import ExtensionStateCommand
from openzyme_extension_spi import ExtensionStateMutation
from openzyme_extension_spi import ExtensionStateMutationKind
from openzyme_extension_spi import ExtensionStateReader
from openzyme_extension_spi import ExtensionStateWriter
from openzyme_extension_spi import ExtensionTransactionBudget


COMPUTE_TRANSACTION_PARTICIPANT_ID = "openzyme.compute.transaction@1"
COMPUTE_STATE_NAMESPACE = "openzyme_compute"


class ComputeTransactionParticipant:
    """Prepare only bounded namespaced state changes; external effects are forbidden."""

    participant_id = COMPUTE_TRANSACTION_PARTICIPANT_ID
    state_namespace = COMPUTE_STATE_NAMESPACE

    def prepare(
        self,
        command: ExtensionStateCommand,
        state: ExtensionStateReader,
    ) -> ExtensionMutationPlan:
        if (
            command.participant_id != self.participant_id
            or command.namespace != self.state_namespace
            or command.context.owner_plugin_id != "openzyme.compute"
            or command.operation != "upsert_execution"
        ):
            raise ValueError("Compute transaction command crossed its exact namespace")
        payload = dict(command.payload)
        if set(payload) != {"execution_id", "expected_state_version", "record"}:
            raise ValueError("Compute transaction payload fields are closed")
        execution_id = payload["execution_id"]
        expected = payload["expected_state_version"]
        record = payload["record"]
        if not isinstance(execution_id, str) or not execution_id:
            raise ValueError("execution_id must be non-empty")
        if expected is not None and (
            not isinstance(expected, int) or isinstance(expected, bool) or expected < 1
        ):
            raise ValueError("expected_state_version must be positive or null")
        if not isinstance(record, Mapping):
            raise ValueError("record must be a closed JSON object")
        current = state.get(
            namespace=self.state_namespace,
            entity_kind="execution",
            entity_id=execution_id,
        )
        if current is not None and expected is None:
            raise ValueError("Compute execution already exists")
        mutation = ExtensionStateMutation(
            mutation_kind=ExtensionStateMutationKind.UPSERT,
            namespace=self.state_namespace,
            entity_kind="execution",
            entity_id=execution_id,
            expected_state_version=expected,
            payload=dict(record),
        )
        return ExtensionMutationPlan.create(
            plan_id=f"compute-plan-{command.context.command_id}",
            participant_id=self.participant_id,
            namespace=self.state_namespace,
            command_id=command.context.command_id,
            mutations=(mutation,),
            budget=ExtensionTransactionBudget(
                max_reads=1,
                max_mutations=1,
                max_payload_bytes=262_144,
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
            raise ValueError("Compute mutation plan crossed its exact participant")
        record = state.upsert(plan.mutations[0])
        result: dict[str, JsonValue] = {
            "execution_id": record.entity_id,
            "state_version": record.state_version,
            "fallback_performed": False,
        }
        return ExtensionMutationResult.create(
            plan_id=plan.plan_id,
            participant_id=self.participant_id,
            namespace=self.state_namespace,
            mutation_applied=True,
            changed_records=(record,),
            result=result,
        )


__all__ = [
    "COMPUTE_STATE_NAMESPACE",
    "COMPUTE_TRANSACTION_PARTICIPANT_ID",
    "ComputeTransactionParticipant",
]
