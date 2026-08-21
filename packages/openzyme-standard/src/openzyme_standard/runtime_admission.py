from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentRuntimeSignal
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import SessionRuntimeLease
from openzyme_contracts import canonical_sha256_digest
from openzyme_kernel import DeclaredToolCatalog
from openzyme_kernel import ExtensionBundleRegistry
from openzyme_kernel import KernelContractError
from openzyme_kernel import RuntimeToolScope
from openzyme_kernel import RuntimeTurnAdmission
from openzyme_kernel import RuntimeTurnBudget
from openzyme_kernel import ToolAffordanceContext
from openzyme_kernel import resolve_tool_affordance_snapshot
from openzyme_kernel import subject_policy_digest
from openzyme_runtime_spi import RuntimeMessage
from openzyme_runtime_spi import RuntimeMessageRole

from .composition import StandardDeploymentStartup
from .composition import StandardPluginFreeCapabilityRegistryResolver


@dataclass(slots=True)
class StandardKernelRuntimeAdmissionSource:
    """Build target-Agent runtime facts from the activated Standard read model.

    The short-lived scope cache contains no canonical truth.  It only gives the
    synchronous capability gateway the exact immutable catalog/snapshot/context used
    to build an already-admitted command.  Restart never reconstructs or redispatches
    a command from this cache.
    """

    records: KernelRecordQueryPort
    startup: StandardDeploymentStartup
    declared_catalog: DeclaredToolCatalog
    extension_registry: ExtensionBundleRegistry
    capability_registries: StandardPluginFreeCapabilityRegistryResolver
    runtime_adapter_id: str
    runtime_adapter_contract_digest: str
    maximum_messages: int = 256
    _scopes: dict[str, RuntimeToolScope] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if not 1 <= self.maximum_messages <= 512:
            raise ValueError("maximum_messages must be between 1 and 512")
        active = self.startup.gate.active_epoch
        if active is None:
            raise ValueError("Standard runtime admission requires an active epoch")
        if (
            self.declared_catalog.catalog_digest
            != active.release_identity.declared_tool_catalog_digest
            or self.extension_registry.extension_bundle_digest
            != active.release_identity.extension_bundle_digest
        ):
            raise ValueError("Standard runtime catalogs differ from activation")

    def pending_signals(
        self,
        *,
        session_id: str,
        maximum: int,
    ) -> tuple[KernelRecordSnapshot, ...]:
        if not 1 <= maximum <= 64:
            raise ValueError("maximum pending runtime signals must be between 1 and 64")
        records = self.records.list_for_session(
            entity_type="agent_runtime_signal",
            session_id=session_id,
            max_items=512,
        )
        pending = tuple(
            sorted(
                (
                    item
                    for item in records
                    if item.payload.get("status") == "pending"
                    and item.payload.get("session_id") == session_id
                ),
                key=lambda item: (
                    str(item.payload.get("created_at", "")),
                    item.entity_id,
                ),
            )
        )
        return pending[:maximum]

    def build_admission(
        self,
        *,
        signal: AgentRuntimeSignal,
        signal_claim_token: str,
        session_lease: SessionRuntimeLease,
        runtime_lease_generation: int,
        command_id: str,
        turn_id: str,
        budget: RuntimeTurnBudget,
        observed_at: str,
    ) -> RuntimeTurnAdmission:
        active = self.startup.gate.active_epoch
        assert active is not None
        raw_signal = self.records.read(
            entity_type="agent_runtime_signal",
            entity_id=signal.signal_id,
        )
        if raw_signal is None:
            raise KernelContractError(
                "runtime_admission_signal_missing",
                "Claimed runtime signal is absent",
            )
        member_id = raw_signal.payload.get("agent_member_id")
        process_epoch = raw_signal.payload.get("process_epoch")
        if (
            not isinstance(member_id, str)
            or not member_id
            or not isinstance(process_epoch, int)
            or isinstance(process_epoch, bool)
            or process_epoch < 1
        ):
            raise KernelContractError(
                "runtime_admission_target_invalid",
                "Runtime signal has no exact target member/process epoch",
            )
        member = self.records.read(entity_type="agent_member", entity_id=member_id)
        if (
            member is None
            or member.payload.get("session_id") != signal.session_id
            or member.payload.get("agent_id") != signal.agent_id
            or member.payload.get("process_epoch") != process_epoch
            or member.payload.get("status") != "active"
        ):
            raise KernelContractError(
                "runtime_admission_member_stale",
                "Runtime target member is absent, retired or restarted",
            )
        lease_id = signal.capability_lease_id
        if lease_id is None:
            raise KernelContractError(
                "runtime_admission_authority_missing",
                "Runtime signal has no Agent authority identity",
            )
        authority_record = self.records.read(
            entity_type="agent_authority_lease",
            entity_id=lease_id,
        )
        try:
            authority = (
                None
                if authority_record is None
                else AgentAuthorityLease.from_dict(authority_record.payload)
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "runtime_admission_authority_invalid",
                "Runtime target authority violates its closed contract",
            ) from exc
        if (
            authority is None
            or authority.agent_member_id != member_id
            or authority.lease_digest != raw_signal.payload.get("capability_lease_digest")
            or authority.workspace_generation != signal.workspace_generation
        ):
            raise KernelContractError(
                "runtime_admission_authority_stale",
                "Runtime signal differs from current Agent authority",
            )
        binding = self._latest_binding(signal.session_id)
        pin = self._composition_pin(signal.session_id)
        if (
            pin.deployment_activation_digest != active.activation_digest
            or pin.release_identity != active.release_identity
            or binding.extension_bundle_digest
            != active.release_identity.extension_bundle_digest
        ):
            raise KernelContractError(
                "runtime_admission_composition_stale",
                "Runtime Session is pinned to another composition",
            )
        registry = self.capability_registries.resolve(binding)
        workspace_generation, workspace_ready, workspace_digest = self._workspace(
            session_id=signal.session_id,
            member_id=member_id,
            expected_generation=signal.workspace_generation,
        )
        role = member.payload.get("role")
        if not isinstance(role, str) or not role:
            raise KernelContractError(
                "runtime_admission_role_invalid",
                "Runtime target role is invalid",
            )
        policy_digest = subject_policy_digest(
            session_id=signal.session_id,
            agent_member_id=member_id,
            subject_role=role,
            task_id=signal.task_id,
            decisions=(),
        )
        health_digest = canonical_sha256_digest(
            {
                "registry_digest": registry.registry_digest,
                "workspace_digest": workspace_digest,
                "authority_lease_digest": authority.lease_digest,
            }
        )
        affordance_context = ToolAffordanceContext(
            session_id=signal.session_id,
            agent_member_id=member_id,
            turn_id=turn_id,
            declared_catalog=self.declared_catalog,
            capability_binding=binding,
            capability_registry=registry,
            authority_lease=authority,
            workspace_generation=workspace_generation,
            workspace_ready=workspace_ready,
            health_observation_digest=health_digest,
            observed_at=observed_at,
            subject_role=role,
            task_id=signal.task_id,
            subject_policy_digest=policy_digest,
        )
        snapshot = resolve_tool_affordance_snapshot(
            affordance_context,
            snapshot_id=f"affordance-{turn_id}",
            created_at=observed_at,
        )
        self._scopes[command_id] = RuntimeToolScope(
            command_id=command_id,
            catalog=self.declared_catalog,
            snapshot=snapshot,
            current_context=affordance_context,
        )
        return RuntimeTurnAdmission(
            command_id=command_id,
            turn_id=turn_id,
            agent_member_id=member_id,
            signal_claim_token=signal_claim_token,
            signal=signal,
            session_lease=session_lease,
            runtime_lease_generation=runtime_lease_generation,
            process_epoch=process_epoch,
            distribution_id=active.distribution_id,
            distribution_manifest_digest=active.distribution_manifest_digest,
            release_identity=active.release_identity,
            capability_binding=binding,
            affordance_snapshot=snapshot,
            runtime_adapter_id=self.runtime_adapter_id,
            runtime_adapter_contract_digest=self.runtime_adapter_contract_digest,
            budget=budget,
            messages=self._messages(signal=signal, member_id=member_id),
            observed_at=observed_at,
        )

    def get(self, command_id: str) -> RuntimeToolScope | None:
        return self._scopes.get(command_id)

    def discard(self, command_id: str) -> None:
        self._scopes.pop(command_id, None)

    def _latest_binding(self, session_id: str) -> SessionCapabilityBindingRevision:
        records = self.records.list_for_session(
            entity_type="session_capability_binding_revision",
            session_id=session_id,
            max_items=64,
        )
        try:
            bindings = tuple(
                SessionCapabilityBindingRevision.from_dict(item.payload)
                for item in records
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "runtime_admission_binding_invalid",
                "Session capability binding is invalid",
            ) from exc
        if not bindings:
            raise KernelContractError(
                "runtime_admission_binding_missing",
                "Session capability binding is absent",
            )
        latest_revision = max(item.revision for item in bindings)
        latest = tuple(item for item in bindings if item.revision == latest_revision)
        if len(latest) != 1:
            raise KernelContractError(
                "runtime_admission_binding_ambiguous",
                "Latest Session capability binding is ambiguous",
            )
        return latest[0]

    def _composition_pin(self, session_id: str) -> SessionCompositionPin:
        records = self.records.list_for_session(
            entity_type="session_composition_pin",
            session_id=session_id,
            max_items=2,
        )
        try:
            if len(records) != 1:
                raise ValueError("missing")
            return SessionCompositionPin.from_dict(records[0].payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "runtime_admission_composition_missing",
                "Session composition pin is absent or invalid",
            ) from exc

    def _workspace(
        self,
        *,
        session_id: str,
        member_id: str,
        expected_generation: int | None,
    ) -> tuple[int, bool, str]:
        records = self.records.list_for_session(
            entity_type="workspace_runtime_binding",
            session_id=session_id,
            max_items=16,
        )
        matches = tuple(
            item
            for item in records
            if item.payload.get("owner_member_id") == member_id
            and item.payload.get("workspace_kind") == "agent_local"
        )
        if len(matches) != 1:
            raise KernelContractError(
                "runtime_admission_workspace_ambiguous",
                "Runtime target requires one exact local workspace",
            )
        generation = matches[0].payload.get("generation")
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
        ):
            raise KernelContractError(
                "runtime_admission_workspace_invalid",
                "Runtime target workspace generation is invalid",
            )
        generation_record = self.records.read(
            entity_type="workspace_generation",
            entity_id=matches[0].entity_id,
        )
        ready = (
            generation_record is not None
            and generation_record.payload.get("session_id") == session_id
            and generation_record.payload.get("owner_member_id") == member_id
            and generation_record.payload.get("generation") == generation
            and generation_record.payload.get("status") == "ready"
            and generation_record.payload.get("root_identity_digest")
            == matches[0].payload.get("root_identity_digest")
            and generation == expected_generation
        )
        workspace_digest = canonical_sha256_digest(
            {
                "runtime_binding_digest": matches[0].record_digest,
                "generation_record_digest": (
                    None
                    if generation_record is None
                    else generation_record.record_digest
                ),
                "ready": ready,
            }
        )
        return generation, ready, workspace_digest

    def _messages(
        self,
        *,
        signal: AgentRuntimeSignal,
        member_id: str,
    ) -> tuple[RuntimeMessage, ...]:
        records = self.records.list_for_session(
            entity_type="conversation_message",
            session_id=signal.session_id,
            max_items=self.maximum_messages,
        )
        ordered = sorted(
            records,
            key=lambda item: (
                str(item.payload.get("created_at", "")),
                item.entity_id,
            ),
        )[-self.maximum_messages :]
        messages: list[RuntimeMessage] = []
        for record in ordered:
            content = record.payload.get("content")
            sender = record.payload.get("sender_actor_id")
            if not isinstance(content, str) or not content:
                continue
            messages.append(
                RuntimeMessage(
                    message_id=record.entity_id,
                    role=(
                        RuntimeMessageRole.ASSISTANT
                        if sender == member_id
                        else RuntimeMessageRole.USER
                    ),
                    content=content,
                    correlation_id=(
                        str(record.payload["correlation_id"])
                        if isinstance(record.payload.get("correlation_id"), str)
                        else None
                    ),
                )
            )
        if not messages:
            messages.append(
                RuntimeMessage(
                    message_id=f"wake-{signal.signal_id}",
                    role=RuntimeMessageRole.SYSTEM,
                    content=(
                        "Process the exact canonical wake signal within this bounded turn."
                    ),
                    correlation_id=signal.correlation_id,
                )
            )
        return tuple(messages)


__all__ = ["StandardKernelRuntimeAdmissionSource"]
