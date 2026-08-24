from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentRuntimeSignal
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import RuntimeContextSectionKind
from openzyme_contracts import RuntimeSignalAuthorityLink
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import SessionRuntimeLease
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityStatus
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
from openzyme_kernel.collaboration_tools import ResolvedCollaborationToolContext
from openzyme_kernel.runtime_context import RuntimeTurnContextBuildRequest
from openzyme_kernel.runtime_context import RuntimeTurnContextBuilder
from openzyme_kernel.tool_exposure import resolve_tool_exposure_role_policy
from openzyme_kernel.tool_exposure import resolve_tool_exposure_snapshot
from openzyme_runtime_spi import RuntimeMessage
from openzyme_runtime_spi import RuntimeMessageRole
from openzyme_runtime_spi import RuntimeTurnCommand
from openzyme_contracts import ToolInvocation
from openzyme_extension_spi import KernelCommandContext
from openzyme_contracts.identity import JsonValue
from collections.abc import Mapping

from .composition import StandardDeploymentStartup
from .composition import StandardPluginFreeCapabilityRegistryResolver
from .role_policies import standard_subject_policy_decisions
from .role_policies import standard_tool_exposure_policies


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
    workflow_registry_snapshot_digest: str
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
        if not self.workflow_registry_snapshot_digest.startswith("sha256:"):
            raise ValueError("Standard workflow registry digest must be exact")

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
            or authority.lease_digest
            != raw_signal.payload.get("capability_lease_digest")
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
        policy_decisions = standard_subject_policy_decisions(
            self.declared_catalog,
            subject_role=role,
        )
        policy_digest = subject_policy_digest(
            session_id=signal.session_id,
            agent_member_id=member_id,
            subject_role=role,
            task_id=signal.task_id,
            decisions=policy_decisions,
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
            policy_decisions=policy_decisions,
        )
        snapshot = resolve_tool_affordance_snapshot(
            affordance_context,
            snapshot_id=f"affordance-{turn_id}",
            created_at=observed_at,
        )
        workflow_authority, signal_authority_link = self._workflow_authority(
            signal=signal,
            member_id=member_id,
        )
        exposure_policy = resolve_tool_exposure_role_policy(
            policies=standard_tool_exposure_policies(
                self.declared_catalog,
                release_digest=active.release_identity.release_digest,
            ),
            distribution_id=active.distribution_id,
            adopted_release_digest=active.release_identity.release_digest,
            subject_role=role,
            catalog=self.declared_catalog,
        )
        exposure = resolve_tool_exposure_snapshot(
            snapshot_id=f"tool-exposure-{turn_id}",
            session_id=signal.session_id,
            agent_member_id=member_id,
            turn_id=turn_id,
            catalog=self.declared_catalog,
            affordance_snapshot=snapshot,
            workflow_binding=workflow_authority,
            policy=exposure_policy,
            adopted_release_digest=active.release_identity.release_digest,
            created_at=observed_at,
        )
        context = RuntimeTurnContextBuilder(reader=self.records).build(
            RuntimeTurnContextBuildRequest(
                context_id=f"runtime-context-{turn_id}",
                session_id=signal.session_id,
                agent_id=signal.agent_id,
                agent_member_id=member_id,
                turn_id=turn_id,
                signal_id=signal.signal_id,
                request_lineage_id=workflow_authority.request_lineage_id,
                created_at=observed_at,
                workflow_binding=workflow_authority,
                signal_authority_link=signal_authority_link,
                capability_binding=binding,
                affordance_snapshot=snapshot,
                exposure_snapshot=exposure,
                task_id=signal.task_id,
                lane_id=signal.lane_id,
            )
        )
        self._scopes[command_id] = RuntimeToolScope(
            command_id=command_id,
            catalog=self.declared_catalog,
            snapshot=snapshot,
            current_context=affordance_context,
            exposure_snapshot=exposure,
            current_workflow_authority=workflow_authority,
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
            workflow_authority=workflow_authority,
            signal_authority_link=signal_authority_link,
            tool_exposure_snapshot=exposure,
            context=context,
            runtime_adapter_id=self.runtime_adapter_id,
            runtime_adapter_contract_digest=self.runtime_adapter_contract_digest,
            budget=budget,
            messages=self._messages(signal=signal),
            observed_at=observed_at,
        )

    def _workflow_authority(
        self,
        *,
        signal: AgentRuntimeSignal,
        member_id: str,
    ) -> tuple[WorkflowAuthorityBinding, RuntimeSignalAuthorityLink]:
        link_record = self.records.read(
            entity_type="runtime_signal_authority_link",
            entity_id=signal.signal_id,
        )
        try:
            if link_record is None:
                raise ValueError("missing")
            link = RuntimeSignalAuthorityLink.from_dict(link_record.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workflow_authority_link_missing",
                "Runtime signal lacks an exact current workflow authority link",
            ) from exc
        binding_record = self.records.read(
            entity_type="workflow_authority_binding",
            entity_id=link.authority_id,
        )
        try:
            if binding_record is None:
                raise ValueError("missing")
            binding = WorkflowAuthorityBinding.from_dict(binding_record.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workflow_authority_binding_missing",
                "Runtime signal workflow authority binding is absent or invalid",
            ) from exc
        if (
            link.signal_id != signal.signal_id
            or link.session_id != signal.session_id
            or link.authority_epoch != binding.epoch
            or link.authority_binding_digest != binding.binding_digest
            or binding.session_id != signal.session_id
            or binding.authorized_actor_id != member_id
            or binding.status is not WorkflowAuthorityStatus.ACTIVE
            or (binding.task_id is not None and binding.task_id != signal.task_id)
            or (binding.lane_id is not None and binding.lane_id != signal.lane_id)
            or binding.registry_snapshot_digest
            != self.workflow_registry_snapshot_digest
        ):
            raise KernelContractError(
                "workflow_authority_stale",
                "Runtime signal and current workflow authority differ",
                details={
                    "signal_id": signal.signal_id,
                    "fallback_performed": False,
                },
            )
        return binding, link

    def get(self, command_id: str) -> RuntimeToolScope | None:
        return self._scopes.get(command_id)

    def resolve(
        self,
        invocation: ToolInvocation,
        *,
        effectful: bool,
    ) -> ResolvedCollaborationToolContext:
        matches = tuple(
            scope
            for scope in self._scopes.values()
            if scope.snapshot.session_id == invocation.session_id
            and scope.snapshot.agent_member_id == invocation.agent_member_id
            and scope.snapshot.snapshot_digest == invocation.affordance_snapshot_digest
        )
        if len(matches) != 1:
            raise KernelContractError(
                "collaboration_tool_runtime_scope_unresolved",
                "Tool invocation has no unique current runtime command scope",
            )
        scope = matches[0]
        workflow = scope.current_workflow_authority
        exposure = scope.exposure_snapshot
        if workflow is None or exposure is None:
            raise KernelContractError(
                "collaboration_tool_runtime_scope_incomplete",
                "Tool invocation scope lacks workflow and exposure authority",
            )
        workflow_record = self.records.read(
            entity_type="workflow_authority_binding",
            entity_id=workflow.authority_id,
        )
        authority_record = self.records.read(
            entity_type="agent_authority_lease",
            entity_id=scope.current_context.authority_lease.lease_id,
        )
        session = self.records.read(
            entity_type="session",
            entity_id=invocation.session_id,
        )
        try:
            if workflow_record is None or authority_record is None or session is None:
                raise ValueError("missing")
            current_workflow = WorkflowAuthorityBinding.from_dict(
                workflow_record.payload
            )
            current_authority = AgentAuthorityLease.from_dict(authority_record.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "collaboration_tool_current_authority_invalid",
                "Tool dispatch current authority graph is invalid",
            ) from exc
        binding = self._latest_binding(invocation.session_id)
        if (
            current_workflow.binding_digest != workflow.binding_digest
            or current_workflow.status is not WorkflowAuthorityStatus.ACTIVE
            or current_authority.lease_digest
            != scope.current_context.authority_lease.lease_digest
            or binding.binding_digest
            != scope.current_context.capability_binding.binding_digest
            or (effectful and not scope.current_context.workspace_ready)
        ):
            raise KernelContractError(
                "collaboration_tool_current_authority_stale",
                "Tool dispatch authority, binding or workspace changed",
            )
        stable = canonical_sha256_digest(
            {
                "runtime_command_id": scope.command_id,
                "call_id": invocation.call_id,
                "tool_name": invocation.tool_name,
            }
        ).removeprefix("sha256:")[:32]
        return ResolvedCollaborationToolContext(
            command_context=KernelCommandContext(
                command_id=f"tool-context-{stable}",
                session_id=invocation.session_id,
                actor_id=invocation.agent_member_id,
                owner_plugin_id="openzyme.kernel",
                authority_lease_id=current_authority.lease_id,
                authority_generation=current_authority.generation,
                authority_fence=current_authority.fence,
                expected_session_version=session.state_version,
                extension_bundle_digest=binding.extension_bundle_digest,
                capability_binding_digest=binding.binding_digest,
                idempotency_key=f"tool-context-{stable}",
                correlation_id=invocation.call_id,
                workspace_generation=current_authority.workspace_generation,
            ),
            runtime_command_id=scope.command_id,
            workflow_authority_id=current_workflow.authority_id,
            workflow_authority_epoch=current_workflow.epoch,
            workflow_authority_digest=current_workflow.binding_digest,
        )

    def inspect(
        self,
        *,
        context: ResolvedCollaborationToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]:
        command_record = self.records.read(
            entity_type="runtime_turn_command",
            entity_id=context.runtime_command_id,
        )
        try:
            if command_record is None:
                raise ValueError("missing")
            command = RuntimeTurnCommand.from_dict(command_record.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "world_inspection_runtime_command_invalid",
                "World inspection requires the canonical runtime command",
            ) from exc
        requested = arguments.get("sections")
        if requested is None:
            kinds = tuple(RuntimeContextSectionKind)
        elif isinstance(requested, tuple | list) and all(
            isinstance(item, str) for item in requested
        ):
            try:
                kinds = tuple(RuntimeContextSectionKind(item) for item in requested)
            except ValueError as exc:
                raise KernelContractError(
                    "world_inspection_section_unknown",
                    "World inspection section name is unknown",
                ) from exc
        else:
            raise ValueError("sections must be an array of exact section names")
        maximum = arguments.get("max_items", 200)
        if (
            not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not 1 <= maximum <= 200
        ):
            raise ValueError("max_items must be between 1 and 200")
        sections: list[JsonValue] = []
        remaining = maximum
        for kind in kinds:
            section = command.context.section(kind)
            kept = section.items[:remaining]
            sections.append(
                {
                    "kind": kind.value,
                    "items": list(kept),
                    "omitted_count": (
                        section.omitted_count + len(section.items) - len(kept)
                    ),
                    "source_section_digest": section.section_digest,
                }
            )
            remaining -= len(kept)
            if remaining == 0:
                break
        return {
            "context_id": command.context.context_id,
            "context_digest": command.context.context_digest,
            "sections": sections,
            "cursor": arguments.get("cursor"),
            "fallback_performed": False,
        }

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
        tool_call_ids = self._tool_call_ids(signal.session_id)
        messages: list[RuntimeMessage] = []
        for record in ordered:
            content = record.payload.get("content")
            sender_kind = record.payload.get("sender_kind")
            if not isinstance(content, str) or not content:
                continue
            tool_call_id = None
            if sender_kind == "tool":
                tool_call_id = tool_call_ids.get(record.entity_id)
                if tool_call_id is None:
                    raise KernelContractError(
                        "runtime_transcript_tool_identity_missing",
                        "Canonical tool transcript lacks its exact tool call identity",
                        details={
                            "message_id": record.entity_id,
                            "fallback_performed": False,
                        },
                    )
            messages.append(
                RuntimeMessage(
                    message_id=record.entity_id,
                    role=(
                        RuntimeMessageRole.ASSISTANT
                        if sender_kind == "assistant"
                        else (
                            RuntimeMessageRole.TOOL
                            if sender_kind == "tool"
                            else RuntimeMessageRole.USER
                        )
                    ),
                    content=content,
                    correlation_id=(
                        str(record.payload["correlation_id"])
                        if isinstance(record.payload.get("correlation_id"), str)
                        else None
                    ),
                    tool_call_id=tool_call_id,
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

    def _tool_call_ids(self, session_id: str) -> dict[str, str]:
        """Recover exact tool-call identities from canonical outcome receipts."""

        identities: dict[str, str] = {}
        outcomes = self.records.list_for_session(
            entity_type="runtime_turn_outcome",
            session_id=session_id,
            max_items=self.maximum_messages,
        )
        for record in outcomes:
            outcome = record.payload.get("outcome")
            if not isinstance(outcome, Mapping):
                raise KernelContractError(
                    "runtime_transcript_outcome_invalid",
                    "Canonical runtime outcome receipt is invalid",
                )
            raw_messages = outcome.get("messages")
            if not isinstance(raw_messages, tuple | list):
                raise KernelContractError(
                    "runtime_transcript_outcome_invalid",
                    "Canonical runtime outcome messages are invalid",
                )
            for raw in raw_messages:
                if not isinstance(raw, Mapping) or raw.get("role") != "tool":
                    continue
                message_id = raw.get("message_id")
                tool_call_id = raw.get("tool_call_id")
                if (
                    not isinstance(message_id, str)
                    or not message_id
                    or not isinstance(tool_call_id, str)
                    or not tool_call_id
                ):
                    raise KernelContractError(
                        "runtime_transcript_tool_identity_invalid",
                        "Canonical tool outcome message identity is invalid",
                    )
                previous = identities.setdefault(message_id, tool_call_id)
                if previous != tool_call_id:
                    raise KernelContractError(
                        "runtime_transcript_tool_identity_ambiguous",
                        "Tool transcript message maps to multiple call identities",
                    )
        return identities


__all__ = ["StandardKernelRuntimeAdmissionSource"]
