"""Deterministic, side-effect-free Ports for Kernel qualification profiles.

These implementations deliberately live outside the production composition root.  They
exercise the same Contracts Ports as real Adapters without importing SQLite, Git,
providers, containers, Plugins, or delivery surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Final
from typing import TYPE_CHECKING

from openzyme_contracts import ControlledEffectCancellationRequest
from openzyme_contracts import ControlledEffectObservationRequest
from openzyme_contracts import ControlledOperationDispatchRequest
from openzyme_contracts import ControlledOperationProviderDispatchReceipt
from openzyme_contracts import ControlledOperationProviderObservationReceipt
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import PublishedRevision
from openzyme_contracts import RemotePrivateRefObservation
from openzyme_contracts import RevisionCommitObservation
from openzyme_contracts import RevisionManifestObservation
from openzyme_contracts import RevisionPathReadReceipt
from openzyme_contracts import RevisionPathReadRequest
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import RevisionPathVerificationReceipt
from openzyme_contracts import UnitOfWorkReceipt
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkspaceCheckpointProofInput
from openzyme_contracts import WorkspaceExecRequest
from openzyme_contracts import WorkspaceFilesystemMutation
from openzyme_contracts import WorkspaceObservation
from openzyme_contracts import WorkspaceObservationRequest
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import WorkspacePublicationDispatchIdentity
from openzyme_contracts import WorkspacePublicationIntent
from openzyme_contracts import WorkspacePublicationRemoteReceipt
from openzyme_contracts import WorkspaceTransferRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_runtime_spi import RuntimeCapabilityGateway
from openzyme_runtime_spi import RuntimeTurnCommand
from openzyme_runtime_spi import RuntimeTurnOutcome

from .errors import KernelContractError


if TYPE_CHECKING:
    from collections.abc import Hashable


_PROVIDER_ID: Final = "openzyme.testing.in-memory-control-store"
_PROVIDER_CONTRACT_DIGEST: Final = canonical_sha256_digest(
    {
        "contract": "openzyme.control-store-port@1",
        "provider": _PROVIDER_ID,
        "external_io": False,
        "atomic_copy_on_commit": True,
    }
)


@dataclass(slots=True)
class DeterministicClock:
    """Manually advanced timezone-aware clock."""

    instant: datetime

    def __post_init__(self) -> None:
        if self.instant.tzinfo is None or self.instant.utcoffset() is None:
            raise ValueError("DeterministicClock instant must be timezone-aware")

    def now_iso(self) -> str:
        return self.instant.isoformat()

    def advance(self, *, seconds: int) -> None:
        if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0:
            raise ValueError("clock advance must be a non-negative integer")
        self.instant += timedelta(seconds=seconds)


@dataclass(slots=True)
class DeterministicIdGenerator:
    """Monotonic deterministic IDs, scoped only by caller-provided namespace."""

    sequence: int = 0

    def new_id(self, *, namespace: str) -> str:
        if not namespace or any(character.isspace() for character in namespace):
            raise ValueError("ID namespace must be non-empty and whitespace-free")
        self.sequence += 1
        return f"{namespace}-{self.sequence}"


class InMemoryControlStore:
    """Atomic ControlStorePort used by the closed Kernel fake profile."""

    provider_id = _PROVIDER_ID
    provider_contract_digest = _PROVIDER_CONTRACT_DIGEST

    def __init__(self, records: tuple[KernelRecordSnapshot, ...] = ()) -> None:
        identities = [(item.entity_type, item.entity_id) for item in records]
        if len(identities) != len(set(identities)):
            raise ValueError("initial Kernel record identities must be unique")
        self._records = {
            (item.entity_type, item.entity_id): item for item in records
        }
        self.events: list[DurableEventRecord] = []
        self.outbox: list[OutboxRecord] = []
        self.commit_count = 0

    @property
    def records(self) -> tuple[KernelRecordSnapshot, ...]:
        return tuple(
            self._records[identity] for identity in sorted(self._records)
        )

    def read(
        self,
        *,
        entity_type: str,
        entity_id: str,
    ) -> KernelRecordSnapshot | None:
        return self._records.get((entity_type, entity_id))

    def list_for_session(
        self,
        *,
        entity_type: str,
        session_id: str,
        max_items: int,
    ) -> tuple[KernelRecordSnapshot, ...]:
        if not session_id:
            raise ValueError("session_id must be non-empty")
        if not 1 <= max_items <= 1_000:
            raise ValueError("max_items must be between 1 and 1000")
        return tuple(
            record
            for record in self.records
            if record.entity_type == entity_type
            and record.payload.get("session_id") == session_id
        )[:max_items]

    def list_command_tool_expansions(
        self,
        *,
        session_id: str,
        command_id: str,
        max_items: int,
    ) -> tuple[KernelRecordSnapshot, ...]:
        if not session_id or not command_id:
            raise ValueError("session_id and command_id must be non-empty")
        if not 1 <= max_items <= 1_000:
            raise ValueError("max_items must be between 1 and 1000")
        return tuple(
            record
            for record in self.records
            if record.entity_type == "command_tool_expansion"
            and record.payload.get("session_id") == session_id
            and record.payload.get("command_id") == command_id
        )[:max_items]

    def seed(self, record: KernelRecordSnapshot) -> None:
        identity = (record.entity_type, record.entity_id)
        if identity in self._records:
            raise ValueError("seed cannot replace an existing Kernel record")
        self._records[identity] = record

    def begin(self, request: UnitOfWorkRequest) -> InMemoryKernelUnitOfWork:
        return InMemoryKernelUnitOfWork(store=self, request=request)


class InMemoryKernelUnitOfWork:
    def __init__(
        self,
        *,
        store: InMemoryControlStore,
        request: UnitOfWorkRequest,
    ) -> None:
        self.store = store
        self.request = request
        self._mutations: list[KernelStateMutation] = []
        self._events: list[DurableEventRecord] = []
        self._outbox: list[OutboxRecord] = []
        self._completed = False

    def _require_open(self) -> None:
        if self._completed:
            raise KernelContractError(
                "fake_unit_of_work_closed",
                "A completed fake Unit of Work cannot be reused",
            )

    def read(
        self,
        *,
        entity_type: str,
        entity_id: str,
    ) -> KernelRecordSnapshot | None:
        self._require_open()
        return self.store.read(entity_type=entity_type, entity_id=entity_id)

    def stage(self, mutation: KernelStateMutation) -> None:
        self._require_open()
        if any(item.mutation_id == mutation.mutation_id for item in self._mutations):
            raise KernelContractError(
                "fake_mutation_identity_conflict",
                "Mutation identity is duplicated inside one Unit of Work",
            )
        self._mutations.append(mutation)

    def append_event(self, event: DurableEventRecord) -> None:
        self._require_open()
        if any(item.event_id == event.event_id for item in self._events):
            raise KernelContractError(
                "fake_event_identity_conflict",
                "Event identity is duplicated inside one Unit of Work",
            )
        self._events.append(event)

    def append_outbox(self, record: OutboxRecord) -> None:
        self._require_open()
        if any(item.outbox_id == record.outbox_id for item in self._outbox):
            raise KernelContractError(
                "fake_outbox_identity_conflict",
                "Outbox identity is duplicated inside one Unit of Work",
            )
        self._outbox.append(record)

    def commit(self) -> UnitOfWorkReceipt:
        self._require_open()
        records = dict(self.store._records)
        for mutation in self._mutations:
            identity = (mutation.entity_type, mutation.entity_id)
            current = records.get(identity)
            if mutation.kind is KernelMutationKind.CREATE:
                if current is not None:
                    raise KernelContractError(
                        "fake_record_create_conflict",
                        "Create mutation targets an existing record",
                    )
                next_version = 1
            else:
                if (
                    current is None
                    or current.state_version != mutation.expected_state_version
                ):
                    raise KernelContractError(
                        "fake_record_state_stale",
                        "Replace/delete mutation has a stale state version",
                    )
                next_version = current.state_version + 1
            if mutation.kind is KernelMutationKind.DELETE:
                del records[identity]
            else:
                records[identity] = KernelRecordSnapshot.create(
                    entity_type=mutation.entity_type,
                    entity_id=mutation.entity_id,
                    state_version=next_version,
                    payload=mutation.payload or {},
                )

        existing_event_ids = {item.event_id for item in self.store.events}
        if existing_event_ids.intersection(item.event_id for item in self._events):
            raise KernelContractError(
                "fake_event_identity_conflict",
                "Event identity already exists",
            )
        existing_outbox_ids = {item.outbox_id for item in self.store.outbox}
        if existing_outbox_ids.intersection(item.outbox_id for item in self._outbox):
            raise KernelContractError(
                "fake_outbox_identity_conflict",
                "Outbox identity already exists",
            )
        available_occurrences = existing_event_ids.union(
            item.event_id for item in self._events
        )
        if any(item.occurrence_id not in available_occurrences for item in self._outbox):
            raise KernelContractError(
                "fake_outbox_occurrence_missing",
                "Outbox record does not reference a durable event",
            )

        session = records.get(("session", self.request.session_id))
        if session is None:
            raise KernelContractError(
                "fake_resulting_session_missing",
                "Committed Unit of Work must retain its Session",
            )
        self.store._records = records
        self.store.events.extend(self._events)
        self.store.outbox.extend(self._outbox)
        self.store.commit_count += 1
        self._completed = True
        return UnitOfWorkReceipt.create(
            unit_of_work_id=self.request.unit_of_work_id,
            command_id=self.request.command_id,
            committed=True,
            mutation_digests=tuple(
                item.mutation_digest for item in self._mutations
            ),
            event_digests=tuple(item.event_digest for item in self._events),
            outbox_payload_digests=tuple(
                item.payload_digest for item in self._outbox
            ),
            resulting_session_version=session.state_version,
        )

    def rollback(self) -> None:
        self._completed = True


class ScriptedAgentRuntimeAdapter:
    """Deterministic runtime fake that never calls a model or provider.

    Outcomes are registered against the exact immutable command digest.  A missing
    script or command drift fails closed instead of fabricating an idle outcome.
    """

    adapter_id = "openzyme.testing.scripted-agent-runtime"
    adapter_contract_digest = canonical_sha256_digest(
        {
            "contract": "openzyme.agent-runtime-adapter@1",
            "provider": adapter_id,
            "external_io": False,
            "missing_script": "fail_closed",
        }
    )

    def __init__(self) -> None:
        self._outcomes: dict[str, RuntimeTurnOutcome] = {}
        self.commands: list[RuntimeTurnCommand] = []

    def script(
        self,
        *,
        command: RuntimeTurnCommand,
        outcome: RuntimeTurnOutcome,
    ) -> None:
        if command.runtime_adapter_id != self.adapter_id:
            raise ValueError("runtime command must select this scripted Adapter")
        if command.runtime_adapter_contract_digest != self.adapter_contract_digest:
            raise ValueError("runtime command must bind this Adapter contract")
        if outcome.command_id != command.command_id:
            raise ValueError("runtime outcome must bind the scripted command ID")
        if outcome.command_digest != command.command_digest:
            raise ValueError("runtime outcome must bind the scripted command digest")
        for field_name in (
            "turn_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
            "signal_attempt",
            "runtime_lease_generation",
            "runtime_fence",
            "process_epoch",
        ):
            if getattr(outcome, field_name) != getattr(command, field_name):
                raise ValueError(
                    f"runtime outcome must bind command field {field_name}"
                )
        if command.command_digest in self._outcomes:
            raise ValueError("runtime command digest already has a scripted outcome")
        self._outcomes[command.command_digest] = outcome

    def run_turn(
        self,
        command: RuntimeTurnCommand,
        capability_gateway: RuntimeCapabilityGateway,
    ) -> RuntimeTurnOutcome:
        del capability_gateway
        outcome = self._outcomes.get(command.command_digest)
        if outcome is None:
            raise KernelContractError(
                "fake_runtime_outcome_missing",
                "No deterministic outcome was registered for the exact command",
            )
        self.commands.append(command)
        return outcome


class ScriptedWorkspaceRuntimeAdapter:
    """One no-I/O fake for all four Workspace Runtime Ports.

    Mutation/exec/transfer reconciliation has a distinct script table.  Reconcile
    therefore cannot accidentally call the original dispatch method.
    """

    def __init__(self) -> None:
        self._observations: dict[str, WorkspaceObservation] = {}
        self._dispatch_receipts: dict[str, WorkspaceOperationReceipt] = {}
        self._reconcile_receipts: dict[str, WorkspaceOperationReceipt] = {}
        self.observation_requests: list[WorkspaceObservationRequest] = []
        self.dispatch_requests: list[
            WorkspaceFilesystemMutation | WorkspaceExecRequest | WorkspaceTransferRequest
        ] = []
        self.reconcile_requests: list[
            WorkspaceFilesystemMutation | WorkspaceExecRequest | WorkspaceTransferRequest
        ] = []

    def script_observation(
        self,
        request: WorkspaceObservationRequest,
        observation: WorkspaceObservation,
    ) -> None:
        if observation.workspace_id != request.binding.workspace_id:
            raise ValueError("observation must bind the scripted workspace")
        self._register_once(self._observations, request.query_digest, observation)

    def script_dispatch(
        self,
        request: WorkspaceFilesystemMutation | WorkspaceExecRequest | WorkspaceTransferRequest,
        receipt: WorkspaceOperationReceipt,
    ) -> None:
        self._validate_workspace_receipt(request, receipt)
        self._register_once(self._dispatch_receipts, request.intent_digest, receipt)

    def script_reconcile(
        self,
        request: WorkspaceFilesystemMutation | WorkspaceExecRequest | WorkspaceTransferRequest,
        receipt: WorkspaceOperationReceipt,
    ) -> None:
        self._validate_workspace_receipt(request, receipt)
        self._register_once(self._reconcile_receipts, request.intent_digest, receipt)

    def observe(self, request: WorkspaceObservationRequest) -> WorkspaceObservation:
        result = self._observations.get(request.query_digest)
        if result is None:
            self._missing("observation")
        self.observation_requests.append(request)
        return result

    def mutate(self, request: WorkspaceFilesystemMutation) -> WorkspaceOperationReceipt:
        return self._dispatch(request)

    def execute(self, request: WorkspaceExecRequest) -> WorkspaceOperationReceipt:
        return self._dispatch(request)

    def transfer(self, request: WorkspaceTransferRequest) -> WorkspaceOperationReceipt:
        return self._dispatch(request)

    def reconcile(
        self,
        request: WorkspaceFilesystemMutation | WorkspaceExecRequest | WorkspaceTransferRequest,
    ) -> WorkspaceOperationReceipt:
        receipt = self._reconcile_receipts.get(request.intent_digest)
        if receipt is None:
            self._missing("reconciliation")
        self.reconcile_requests.append(request)
        return receipt

    def _dispatch(
        self,
        request: WorkspaceFilesystemMutation | WorkspaceExecRequest | WorkspaceTransferRequest,
    ) -> WorkspaceOperationReceipt:
        receipt = self._dispatch_receipts.get(request.intent_digest)
        if receipt is None:
            self._missing("dispatch")
        self.dispatch_requests.append(request)
        return receipt

    @staticmethod
    def _validate_workspace_receipt(
        request: WorkspaceFilesystemMutation | WorkspaceExecRequest | WorkspaceTransferRequest,
        receipt: WorkspaceOperationReceipt,
    ) -> None:
        if receipt.operation_id != request.operation_id:
            raise ValueError("workspace receipt must bind the scripted operation")
        if receipt.workspace_id != request.binding.workspace_id:
            raise ValueError("workspace receipt must bind the scripted workspace")
        if receipt.generation != request.binding.generation:
            raise ValueError("workspace receipt must bind the scripted generation")

    @staticmethod
    def _register_once(table: dict["Hashable", object], key: "Hashable", value: object) -> None:
        if key in table:
            raise ValueError("a deterministic fake script cannot be replaced")
        table[key] = value

    @staticmethod
    def _missing(kind: str):  # noqa: ANN205
        raise KernelContractError(
            "fake_workspace_script_missing",
            f"No deterministic workspace {kind} was registered",
        )


class ScriptedControlledEffectAdapter:
    """No-I/O controlled-effect fake with dispatch/observe/cancel separation."""

    provider_id = "openzyme.testing.scripted-controlled-effect"
    provider_contract_digest = canonical_sha256_digest(
        {
            "contract": "openzyme.controlled-effect-adapter@1",
            "provider": provider_id,
            "external_io": False,
            "redispatch_on_observe": False,
        }
    )

    def __init__(self) -> None:
        self._dispatch: dict[str, ControlledOperationProviderDispatchReceipt] = {}
        self._observe: dict[str, ControlledOperationProviderObservationReceipt] = {}
        self._cancel: dict[str, ControlledOperationProviderObservationReceipt] = {}
        self.dispatch_requests: list[ControlledOperationDispatchRequest] = []
        self.observation_requests: list[ControlledEffectObservationRequest] = []
        self.cancellation_requests: list[ControlledEffectCancellationRequest] = []

    def script_dispatch(
        self,
        *,
        request: ControlledOperationDispatchRequest,
        receipt: ControlledOperationProviderDispatchReceipt,
    ) -> None:
        if receipt.execution_id != request.execution_id or receipt.operation_id != request.operation_id:
            raise ValueError("effect dispatch receipt must bind the scripted execution")
        self._register_once(self._dispatch, request.request_digest, receipt)

    def script_observation(
        self,
        *,
        request: ControlledEffectObservationRequest,
        receipt: ControlledOperationProviderObservationReceipt,
    ) -> None:
        if receipt.execution_id != request.execution_id or receipt.operation_id != request.operation_id:
            raise ValueError("effect observation must bind the scripted execution")
        self._register_once(self._observe, self._observation_key(request), receipt)

    def script_cancellation(
        self,
        *,
        request: ControlledEffectCancellationRequest,
        receipt: ControlledOperationProviderObservationReceipt,
    ) -> None:
        if receipt.execution_id != request.execution_id or receipt.operation_id != request.operation_id:
            raise ValueError("effect cancellation must bind the scripted execution")
        self._register_once(self._cancel, self._cancellation_key(request), receipt)

    def dispatch(
        self,
        request: ControlledOperationDispatchRequest,
    ) -> ControlledOperationProviderDispatchReceipt:
        receipt = self._dispatch.get(request.request_digest)
        if receipt is None:
            self._missing("dispatch")
        self.dispatch_requests.append(request)
        return receipt

    def observe(
        self,
        request: ControlledEffectObservationRequest,
    ) -> ControlledOperationProviderObservationReceipt:
        receipt = self._observe.get(self._observation_key(request))
        if receipt is None:
            self._missing("observation")
        self.observation_requests.append(request)
        return receipt

    def cancel(
        self,
        request: ControlledEffectCancellationRequest,
    ) -> ControlledOperationProviderObservationReceipt:
        receipt = self._cancel.get(self._cancellation_key(request))
        if receipt is None:
            self._missing("cancellation")
        self.cancellation_requests.append(request)
        return receipt

    @staticmethod
    def _observation_key(request: ControlledEffectObservationRequest) -> str:
        return canonical_sha256_digest(
            {
                "execution_id": request.execution_id,
                "operation_id": request.operation_id,
                "dispatch_generation": request.dispatch_generation,
                "provider_request_identity": request.provider_request_identity,
                "authority_fence": request.authority_fence,
            }
        )

    @staticmethod
    def _cancellation_key(request: ControlledEffectCancellationRequest) -> str:
        return canonical_sha256_digest(
            {
                "execution_id": request.execution_id,
                "operation_id": request.operation_id,
                "dispatch_generation": request.dispatch_generation,
                "provider_request_identity": request.provider_request_identity,
                "authority_fence": request.authority_fence,
                "cancellation_digest": request.cancellation_digest,
            }
        )

    @staticmethod
    def _register_once(table: dict[str, object], key: str, value: object) -> None:
        if key in table:
            raise ValueError("a deterministic fake script cannot be replaced")
        table[key] = value

    @staticmethod
    def _missing(kind: str):  # noqa: ANN205
        raise KernelContractError(
            "fake_effect_script_missing",
            f"No deterministic controlled-effect {kind} was registered",
        )


class ScriptedWorkspaceRevisionBackend:
    """Deterministic Git-shaped semantic fake; performs no Git or filesystem I/O."""

    def __init__(self) -> None:
        self.private_refs: dict[tuple[str, str], RemotePrivateRefObservation] = {}
        self.commits: dict[tuple[str, str], RevisionCommitObservation] = {}
        self.manifests: dict[tuple[str, str], RevisionManifestObservation] = {}
        self.publications: dict[str, WorkspacePublicationRemoteReceipt] = {}
        self.path_verifications: dict[str, RevisionPathVerificationReceipt] = {}
        self.path_reads: dict[str, RevisionPathReadReceipt] = {}
        self.dispatches: list[WorkspacePublicationDispatchIdentity] = []
        self.observed_publication_receipts: list[str] = []

    def observe_private_ref(
        self,
        binding: ProjectRepositoryBinding,
        proof: WorkspaceCheckpointProofInput,
    ) -> RemotePrivateRefObservation:
        return self._required(self.private_refs, (binding.repository_id, proof.private_ref))

    def observe_commit(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> RevisionCommitObservation:
        return self._required(self.commits, (binding.repository_id, commit))

    def observe_manifest(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> RevisionManifestObservation:
        return self._required(self.manifests, (binding.repository_id, commit))

    def dispatch_publication(
        self,
        binding: ProjectRepositoryBinding,
        intent: WorkspacePublicationIntent,
        dispatch: WorkspacePublicationDispatchIdentity,
    ) -> WorkspacePublicationRemoteReceipt:
        del binding
        receipt = self._required(self.publications, intent.publication_id)
        if receipt.execution_dispatch_generation != dispatch.dispatch_generation:
            raise KernelContractError(
                "fake_revision_dispatch_generation_mismatch",
                "Scripted publication receipt does not bind the dispatch generation",
            )
        self.dispatches.append(dispatch)
        return receipt

    def observe_publication(
        self,
        binding: ProjectRepositoryBinding,
        intent: WorkspacePublicationIntent,
        receipt: WorkspacePublicationRemoteReceipt,
    ) -> WorkspacePublicationRemoteReceipt:
        del binding
        scripted = self._required(self.publications, intent.publication_id)
        if scripted.receipt_digest != receipt.receipt_digest:
            raise KernelContractError(
                "fake_revision_receipt_mismatch",
                "Publication reconciliation requires the exact durable receipt",
            )
        self.observed_publication_receipts.append(receipt.receipt_id)
        return scripted

    def verify_revision_path(
        self,
        binding: ProjectRepositoryBinding,
        revision: PublishedRevision,
        ref: RevisionPathRef,
    ) -> RevisionPathVerificationReceipt:
        del binding, revision
        return self._required(self.path_verifications, ref.ref_id)

    def read_revision_path(
        self,
        binding: ProjectRepositoryBinding,
        request: RevisionPathReadRequest,
    ) -> RevisionPathReadReceipt:
        del binding
        key = canonical_sha256_digest(
            {"ref_digest": request.ref.ref_digest, "max_bytes": request.max_bytes}
        )
        return self._required(self.path_reads, key)

    @staticmethod
    def _required(table, key):  # noqa: ANN001, ANN205
        try:
            return table[key]
        except KeyError as exc:
            raise KernelContractError(
                "fake_revision_script_missing",
                "No deterministic revision response was registered",
            ) from exc


__all__ = [
    "DeterministicClock",
    "DeterministicIdGenerator",
    "InMemoryControlStore",
    "InMemoryKernelUnitOfWork",
    "ScriptedAgentRuntimeAdapter",
    "ScriptedControlledEffectAdapter",
    "ScriptedWorkspaceRevisionBackend",
    "ScriptedWorkspaceRuntimeAdapter",
]
