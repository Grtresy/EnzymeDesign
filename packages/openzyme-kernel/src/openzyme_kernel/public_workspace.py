from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Protocol

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import ClockPort
from openzyme_contracts import CommandToolExpansion
from openzyme_contracts import FailureObservation
from openzyme_contracts import FILE_WORKSPACE_FAILURE_FACT_PUBLIC_FIELDS
from openzyme_contracts import FILE_WORKSPACE_FAILURE_IDENTITY_PUBLIC_FIELDS
from openzyme_contracts import RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_SCHEMA_VERSION
from openzyme_contracts import FileWorkspaceCoreProjectionV2
from openzyme_contracts import FileWorkspaceExtensionSectionV2
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import FileWorkspaceToolReflection
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolExposure
from openzyme_contracts import ToolExposureSnapshot
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import WorkspaceProvisioningIntent
from openzyme_contracts import WorkspaceProvisioningReconciliation
from openzyme_contracts import WorkspaceProvisioningReconciliationStatus
from openzyme_contracts import WorkspaceProvisioningStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import json_compatible
from openzyme_contracts import parse_failure_observation
from openzyme_contracts import validate_command_tool_expansion
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import KernelQueryContext
from openzyme_extension_spi import ProjectionContributor
from openzyme_extension_spi import ProjectionRequest
from openzyme_runtime_spi import RuntimeTurnOutcomeReceipt
from openzyme_runtime_spi import RuntimeTurnCommand

from .catalog import DeclaredToolCatalog
from .affordance import ToolAffordanceContext
from .affordance import ToolSubjectPolicyAction
from .affordance import ToolSubjectPolicyDecision
from .affordance import resolve_tool_affordance_snapshot
from .affordance import subject_policy_digest
from .errors import KernelContractError
from .registry import CapabilityRegistry
from .tool_exposure import ToolExposureRolePolicy
from .tool_exposure import resolve_tool_exposure_role_policy


DEFAULT_PUBLIC_PROJECTION_MAX_BYTES = 4 * 1024 * 1024
DEFAULT_EXTENSION_SECTION_MAX_BYTES = 256 * 1024
DEFAULT_EXTENSION_SECTION_MAX_ITEMS = 200
_FORBIDDEN_PUBLIC_FIELD_FRAGMENTS = (
    "credential",
    "secret",
    "access_token",
    "refresh_token",
    "private_key",
    "host_path",
    "remote_root",
    "login_alias",
    "scheduler_handle",
)
_FORBIDDEN_PUBLIC_FIELD_TOKENS = frozenset(
    {
        "claimtoken",
        "deliveryleasetoken",
        "leasetoken",
        "runtimeleasetoken",
        "sessionleasetoken",
        "signalclaimtoken",
    }
)
_PUBLIC_CORE_ENTITY_TYPES = (
    "agent_authority_lease",
    "agent_member",
    "agent_runtime_signal",
    "approval_request",
    "continuation",
    "controlled_operation",
    "conversation_message",
    "failure_observation",
    "inbox_message",
    "kernel_command_receipt",
    "lane",
    "memory",
    "protocol_record",
    "published_revision",
    "revision_path_verification",
    "runtime_continuation_intent",
    "runtime_command",
    "runtime_outcome_consumption",
    "runtime_settlement_intent",
    "runtime_signal_authority_link",
    "runtime_turn_context",
    "runtime_turn_command",
    "runtime_turn_outcome",
    "session_capability_binding_revision",
    "session_composition_pin",
    "session_repository_binding_pin",
    "session_runtime_lease",
    "task",
    "task_evidence",
    "tool_exposure_snapshot",
    "verified_workspace_checkpoint",
    "workflow_authority_binding",
    "workspace_generation",
    "workspace_provisioning_intent",
    "workspace_provisioning_reconciliation",
    "workspace_publication_intent",
    "workspace_runtime_binding",
    "command_tool_expansion",
)


@dataclass(frozen=True, slots=True)
class KernelCoreProjectionSource:
    """Canonical input to a delivery Adapter's public projection assembly."""

    context: KernelQueryContext
    core_payload: Mapping[str, JsonValue]


class KernelCoreProjectionProvider(Protocol):
    def inspect(
        self,
        *,
        session_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> KernelCoreProjectionSource: ...


class CapabilityRegistryResolverPort(Protocol):
    """Resolve the exact registry adopted by one Session binding revision."""

    def resolve(
        self,
        binding: SessionCapabilityBindingRevision,
    ) -> CapabilityRegistry: ...


@dataclass(frozen=True, slots=True)
class KernelPublicWorkspaceProjectionService:
    """Build the closed Core projection directly from target Kernel records.

    This service owns no persistence and performs no `@1` translation.  Its
    reader is bounded by Session and its capability registry is supplied by the
    active Distribution composition.
    """

    reader: KernelRecordQueryPort
    declared_catalog: DeclaredToolCatalog
    capability_registries: CapabilityRegistryResolverPort
    extension_bundle_digest: str
    distribution_id: str
    adopted_release_digest: str
    subject_policy_decisions_by_role: Mapping[
        str,
        tuple[ToolSubjectPolicyDecision, ...],
    ]
    tool_exposure_policies: tuple[ToolExposureRolePolicy, ...]
    clock: ClockPort
    max_items_per_entity_type: int = 200

    def __post_init__(self) -> None:
        if not 1 <= self.max_items_per_entity_type <= 1_000:
            raise ValueError("max_items_per_entity_type must be between 1 and 1000")
        if not self.distribution_id:
            raise ValueError("public projection requires one Distribution identity")
        if not self.adopted_release_digest.startswith("sha256:"):
            raise ValueError("public projection requires one adopted release digest")
        if not self.subject_policy_decisions_by_role or not self.tool_exposure_policies:
            raise ValueError("public projection requires closed role policies")

    def inspect(
        self,
        *,
        session_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> KernelCoreProjectionSource:
        session = self.reader.read(entity_type="session", entity_id=session_id)
        if session is None or session.payload.get("session_id") != session_id:
            raise KernelContractError(
                "public_projection_session_missing",
                "Session does not exist in the target Kernel store",
                details={"session_id": session_id},
            )
        records = {
            entity_type: self.reader.list_for_session(
                entity_type=entity_type,
                session_id=session_id,
                max_items=self.max_items_per_entity_type,
            )
            for entity_type in _PUBLIC_CORE_ENTITY_TYPES
        }
        subject = self._subject_agent(records["agent_member"], actor_id=actor_id)
        lease_id = subject.payload.get("active_authority_lease_id")
        if not isinstance(lease_id, str) or not lease_id:
            raise KernelContractError(
                "public_projection_authority_missing",
                "Projection subject has no active AgentAuthorityLease identity",
            )
        lease_snapshot = self.reader.read(
            entity_type="agent_authority_lease",
            entity_id=lease_id,
        )
        if (
            lease_snapshot is None
            or lease_snapshot.payload.get("session_id") != session_id
        ):
            raise KernelContractError(
                "public_projection_authority_missing",
                "Projection subject authority lease is absent or belongs elsewhere",
            )
        try:
            lease = AgentAuthorityLease.from_dict(lease_snapshot.payload)
            binding = self._latest_binding(
                records["session_capability_binding_revision"]
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "public_projection_identity_invalid",
                "Projection authority or capability binding violates its closed contract",
            ) from exc
        if binding.extension_bundle_digest != self.extension_bundle_digest:
            raise KernelContractError(
                "public_projection_extension_bundle_drift",
                "Session capability binding names another Extension bundle",
            )
        registry = self.capability_registries.resolve(binding)
        if registry.binding.binding_digest != binding.binding_digest:
            raise KernelContractError(
                "public_projection_capability_registry_drift",
                "Resolved capability registry belongs to another binding",
            )
        workspace_generation, workspace_ready, workspace_state_digest = (
            self._workspace_state(
                records["workspace_runtime_binding"],
                subject_member_id=str(subject.payload["agent_member_id"]),
                expected_generation=subject.payload.get("workspace_generation"),
            )
        )
        observed_at = self.clock.now_iso()
        subject_role = str(subject.payload["role"])
        policy_decisions = self._subject_policy_decisions(subject_role)
        policy_digest = subject_policy_digest(
            session_id=session_id,
            agent_member_id=str(subject.payload["agent_member_id"]),
            subject_role=subject_role,
            task_id=None,
            decisions=policy_decisions,
        )
        health_digest = canonical_sha256_digest(
            {
                "capability_registry_digest": registry.registry_digest,
                "workspace_state_digest": workspace_state_digest,
                "authority_lease_digest": lease.lease_digest,
                "authority_temporally_current": _lease_is_temporally_current(
                    lease,
                    observed_at=observed_at,
                ),
            }
        )
        snapshot_seed = canonical_sha256_digest(
            {
                "session_id": session_id,
                "agent_member_id": subject.payload["agent_member_id"],
                "declared_tool_catalog_digest": self.declared_catalog.catalog_digest,
                "capability_binding_digest": binding.binding_digest,
                "health_observation_digest": health_digest,
                "subject_policy_digest": policy_digest,
            }
        ).removeprefix("sha256:")[:24]
        snapshot = resolve_tool_affordance_snapshot(
            ToolAffordanceContext(
                session_id=session_id,
                agent_member_id=str(subject.payload["agent_member_id"]),
                turn_id=f"public-inspect-{snapshot_seed}",
                declared_catalog=self.declared_catalog,
                capability_binding=binding,
                capability_registry=registry,
                authority_lease=lease,
                workspace_generation=workspace_generation,
                workspace_ready=workspace_ready,
                health_observation_digest=health_digest,
                observed_at=observed_at,
                subject_role=subject_role,
                task_id=None,
                subject_policy_digest=policy_digest,
                policy_decisions=policy_decisions,
            ),
            snapshot_id=f"public-affordance-{snapshot_seed}",
            created_at=_projection_fact_time(
                binding=binding,
                lease=lease,
                subject_payload=subject.payload,
            ),
        )
        reflection = build_public_tool_reflection(
            declared_catalog=self.declared_catalog,
            affordance_snapshot=snapshot,
        )
        reflection_payload = self._current_tool_reflection(
            subject_member_id=str(subject.payload["agent_member_id"]),
            subject_role=subject_role,
            affordance_snapshot=snapshot,
            legacy_reflection=reflection,
            expansion_records=records["command_tool_expansion"],
            exposure_records=records["tool_exposure_snapshot"],
            snapshot_seed=snapshot_seed,
        )
        readiness, provisioning = _resident_workspace_projection(
            subject=subject,
            intents=records["workspace_provisioning_intent"],
            reconciliations=records["workspace_provisioning_reconciliation"],
            generations=records["workspace_generation"],
            runtime_bindings=records["workspace_runtime_binding"],
            failures=records["failure_observation"],
        )
        transcript = _ordered_transcript_projection(
            messages=records["conversation_message"],
            outcomes=records["runtime_turn_outcome"],
        )
        core_payload: dict[str, JsonValue] = {
            "session": {
                **_public_record_payload(session),
                "resident_readiness": readiness,
            },
            "tasks": _payloads(records["task"]),
            "lanes": _payloads(records["lane"]),
            "agents": _payloads(records["agent_member"]),
            "protocol": {
                "records": _payloads(records["protocol_record"]),
                "inbox": _payloads(records["inbox_message"]),
            },
            "conversation": {
                "messages": _public_conversation_payloads(
                    records["conversation_message"]
                ),
                "memories": _payloads(records["memory"]),
                "transcript": transcript,
            },
            "approvals": _payloads(records["approval_request"]),
            "authority_leases": _payloads(records["agent_authority_lease"]),
            "capability_binding": dict(binding.to_dict()),
            "runtime": {
                "signals": _runtime_signal_public(records["agent_runtime_signal"]),
                "session_leases": _session_runtime_lease_public(
                    records["session_runtime_lease"]
                ),
                "turn_commands": _runtime_turn_commands_public(
                    records["runtime_turn_command"]
                ),
                "commands": _runtime_commands_public(
                    records["runtime_command"],
                    failures=records["failure_observation"],
                ),
                "continuation_intents": _payloads(
                    records["runtime_continuation_intent"]
                ),
                "settlement_intents": _payloads(records["runtime_settlement_intent"]),
                "outcome_consumptions": _runtime_outcome_consumptions_public(
                    records["runtime_outcome_consumption"]
                ),
                "outcomes": _runtime_outcomes_public(records["runtime_turn_outcome"]),
                "workflow_authority": {
                    "schema_version": "workflow_authority_projection@1",
                    "bindings": _contract_payloads(
                        records["workflow_authority_binding"]
                    ),
                    "signal_links": _contract_payloads(
                        records["runtime_signal_authority_link"]
                    ),
                },
            },
            "workspace": {
                "generations": _payloads(records["workspace_generation"]),
                "runtime_bindings": _payloads(records["workspace_runtime_binding"]),
                "repository_binding_pins": _payloads(
                    records["session_repository_binding_pin"]
                ),
                "checkpoints": _payloads(records["verified_workspace_checkpoint"]),
                "revision_path_verifications": _payloads(
                    records["revision_path_verification"]
                ),
                "provisioning": provisioning,
            },
            "publications": _payloads(records["published_revision"]),
            "operations": {
                "controlled": _payloads(records["controlled_operation"]),
                "continuations": _payloads(records["continuation"]),
                "publication_intents": _payloads(
                    records["workspace_publication_intent"]
                ),
                "task_evidence": _payloads(records["task_evidence"]),
                "command_receipts": _payloads(records["kernel_command_receipt"]),
            },
            "failures": {
                "observations": _public_failure_payloads(
                    records["failure_observation"]
                ),
            },
            "tool_reflection": reflection_payload,
        }
        # Validate the closed Core and secret/path denylist before a delivery
        # Adapter receives any payload.
        FileWorkspaceCoreProjectionV2(core_payload)
        return KernelCoreProjectionSource(
            context=KernelQueryContext(
                session_id=session_id,
                actor_id=actor_id,
                owner_plugin_id="openzyme.kernel",
                authority_lease_id=lease.lease_id,
                extension_bundle_digest=self.extension_bundle_digest,
                capability_binding_digest=binding.binding_digest,
                correlation_id=correlation_id,
            ),
            core_payload=core_payload,
        )

    def _subject_policy_decisions(
        self,
        subject_role: str,
    ) -> tuple[ToolSubjectPolicyDecision, ...]:
        decisions = self.subject_policy_decisions_by_role.get(subject_role)
        if decisions is None:
            raise KernelContractError(
                "public_projection_subject_policy_missing",
                "Distribution has no exact subject policy for the projected role",
                details={"subject_role": subject_role, "fallback_performed": False},
            )
        catalog_names = {
            entry.contract.tool_name for entry in self.declared_catalog.entries
        }
        decision_names = {decision.tool_name for decision in decisions}
        if len(decision_names) != len(decisions) or decision_names != catalog_names:
            raise KernelContractError(
                "public_projection_subject_policy_catalog_drift",
                "Subject policy must classify every declared tool exactly once",
                details={
                    "subject_role": subject_role,
                    "missing_tool_names": sorted(catalog_names - decision_names),
                    "unknown_tool_names": sorted(decision_names - catalog_names),
                    "fallback_performed": False,
                },
            )
        return tuple(sorted(decisions, key=lambda item: item.tool_name))

    def _current_tool_reflection(
        self,
        *,
        subject_member_id: str,
        subject_role: str,
        affordance_snapshot: ToolAffordanceSnapshot,
        legacy_reflection: FileWorkspaceToolReflection,
        expansion_records: tuple[KernelRecordSnapshot, ...],
        exposure_records: tuple[KernelRecordSnapshot, ...],
        snapshot_seed: str,
    ) -> dict[str, JsonValue]:
        policy = resolve_tool_exposure_role_policy(
            policies=self.tool_exposure_policies,
            distribution_id=self.distribution_id,
            adopted_release_digest=self.adopted_release_digest,
            subject_role=subject_role,
            catalog=self.declared_catalog,
        )
        subject_decisions = {
            item.tool_name: item
            for item in self._subject_policy_decisions(subject_role)
        }
        exposure_decisions = {item.tool_name: item for item in policy.decisions}
        misaligned_hidden = sorted(
            tool_name
            for tool_name, decision in subject_decisions.items()
            if (decision.action is ToolSubjectPolicyAction.HIDE)
            != (exposure_decisions[tool_name].exposure is ToolExposure.HIDDEN)
        )
        if misaligned_hidden:
            raise KernelContractError(
                "public_projection_hidden_policy_drift",
                "Subject and exposure policies disagree about Hidden tools",
                details={
                    "tool_names": misaligned_hidden,
                    "fallback_performed": False,
                },
            )
        disclosed = {
            name
            for name, decision in exposure_decisions.items()
            if decision.exposure is not ToolExposure.HIDDEN
        }
        direct = {
            name
            for name, decision in exposure_decisions.items()
            if decision.exposure is ToolExposure.DIRECT
        }
        deferred = {
            name
            for name, decision in exposure_decisions.items()
            if decision.exposure is ToolExposure.DEFERRED
        }
        affordances = [
            item.to_dict()
            for item in affordance_snapshot.affordances
            if item.tool_name in disclosed and item.state.value != "hidden"
        ]
        available = [
            str(item["tool_name"])
            for item in affordances
            if str(item["tool_name"]) in direct
            and item["state"] in {"available", "available_with_approval"}
        ]
        parsed_snapshots: dict[str, ToolExposureSnapshot] = {}
        for record in exposure_records:
            try:
                parsed = ToolExposureSnapshot.from_dict(_json_contract_payload(record))
            except (TypeError, ValueError) as exc:
                raise KernelContractError(
                    "public_projection_tool_exposure_invalid",
                    "Stored tool exposure snapshot violates its closed contract",
                    details={
                        "exposure_snapshot_id": record.entity_id,
                        "fallback_performed": False,
                    },
                ) from exc
            if parsed.exposure_snapshot_id != record.entity_id:
                raise KernelContractError(
                    "public_projection_tool_exposure_identity_drift",
                    "Stored tool exposure identity differs from its record identity",
                    details={
                        "exposure_snapshot_id": record.entity_id,
                        "fallback_performed": False,
                    },
                )
            parsed_snapshots[parsed.exposure_snapshot_id] = parsed

        expansions: list[dict[str, JsonValue]] = []
        for record in expansion_records:
            try:
                expansion = CommandToolExpansion.from_dict(
                    _json_contract_payload(record)
                )
            except (TypeError, ValueError) as exc:
                raise KernelContractError(
                    "public_projection_command_expansion_invalid",
                    "Stored command expansion violates its closed contract",
                    details={
                        "expansion_id": record.entity_id,
                        "fallback_performed": False,
                    },
                ) from exc
            if expansion.expansion_id != record.entity_id:
                raise KernelContractError(
                    "public_projection_command_expansion_identity_drift",
                    "Stored command expansion identity differs from its record identity",
                    details={
                        "expansion_id": record.entity_id,
                        "fallback_performed": False,
                    },
                )
            exposure_snapshot = parsed_snapshots.get(expansion.exposure_snapshot_id)
            if exposure_snapshot is None:
                raise KernelContractError(
                    "public_projection_command_expansion_exposure_missing",
                    "Command expansion lacks its exact tool exposure snapshot",
                    details={
                        "expansion_id": expansion.expansion_id,
                        "fallback_performed": False,
                    },
                )
            try:
                validate_command_tool_expansion(exposure_snapshot, expansion)
            except ValueError as exc:
                raise KernelContractError(
                    "public_projection_command_expansion_drift",
                    "Command expansion differs from its exact exposure snapshot",
                    details={
                        "expansion_id": expansion.expansion_id,
                        "fallback_performed": False,
                    },
                ) from exc
            if exposure_snapshot.agent_member_id != subject_member_id:
                continue
            observed_exposure = {
                item.tool_name: item.exposure for item in exposure_snapshot.decisions
            }
            expected_exposure = {
                item.tool_name: item.exposure for item in policy.decisions
            }
            if observed_exposure != expected_exposure or not set(
                expansion.expanded_tool_names
            ).issubset(deferred):
                raise KernelContractError(
                    "public_projection_command_expansion_role_policy_drift",
                    "Command expansion differs from the adopted role exposure policy",
                    details={
                        "expansion_id": expansion.expansion_id,
                        "fallback_performed": False,
                    },
                )
            expansions.append(
                {
                    "schema_version": "command_tool_expansion_public@1",
                    "expansion_id": expansion.expansion_id,
                    "command_id": expansion.command_id,
                    "expansion_revision": expansion.expansion_revision,
                    "expanded_tool_names": list(expansion.expanded_tool_names),
                    "expansion_digest": expansion.expansion_digest,
                }
            )
        exposure_payload: dict[str, JsonValue] = {
            "schema_version": "tool_exposure_public@1",
            "exposure_snapshot_id": f"public-exposure-{snapshot_seed}",
            "direct_tool_names": sorted(direct),
            "deferred_tool_names": sorted(deferred),
            "command_expansions": sorted(
                expansions,
                key=lambda item: (
                    str(item["command_id"]),
                    int(item["expansion_revision"]),
                ),
            ),
        }
        exposure_payload["exposure_snapshot_digest"] = canonical_sha256_digest(
            exposure_payload
        )
        legacy = legacy_reflection.to_dict()
        return {
            "declared_tool_catalog_digest": legacy["declared_tool_catalog_digest"],
            "affordance_snapshot_digest": legacy["affordance_snapshot_digest"],
            "capability_binding_digest": legacy["capability_binding_digest"],
            "available_tool_names": available,
            "affordances": affordances,
            "tool_exposure": exposure_payload,
        }

    @staticmethod
    def _subject_agent(
        records: tuple[KernelRecordSnapshot, ...],
        *,
        actor_id: str,
    ) -> KernelRecordSnapshot:
        snapshots = tuple(records)
        requested_member_id = (
            actor_id.removeprefix("agent-member:")
            if actor_id.startswith("agent-member:")
            else None
        )
        if requested_member_id is not None:
            candidates = tuple(
                item
                for item in snapshots
                if item.payload.get("agent_member_id") == requested_member_id
            )
        else:
            candidates = tuple(
                item
                for item in snapshots
                if item.payload.get("parent_agent_id") is None
            )
        if len(candidates) != 1:
            raise KernelContractError(
                "public_projection_subject_ambiguous",
                "Projection requires one exact Session Agent subject",
            )
        return candidates[0]

    @staticmethod
    def _latest_binding(
        records: tuple[KernelRecordSnapshot, ...],
    ) -> SessionCapabilityBindingRevision:
        if not records:
            raise KernelContractError(
                "public_projection_capability_binding_missing",
                "Session has no capability binding revision",
            )
        parsed = tuple(
            SessionCapabilityBindingRevision.from_dict(item.payload) for item in records
        )
        latest_revision = max(item.revision for item in parsed)
        latest = tuple(item for item in parsed if item.revision == latest_revision)
        if len(latest) != 1:
            raise KernelContractError(
                "public_projection_capability_binding_ambiguous",
                "Session latest capability binding revision is ambiguous",
            )
        return latest[0]

    @staticmethod
    def _workspace_state(
        records: tuple[KernelRecordSnapshot, ...],
        *,
        subject_member_id: str,
        expected_generation: JsonValue,
    ) -> tuple[int, bool, str]:
        candidates = tuple(
            item
            for item in records
            if item.payload.get("owner_member_id") == subject_member_id
            and item.payload.get("workspace_kind") == "agent_local"
        )
        if len(candidates) > 1:
            raise KernelContractError(
                "public_projection_workspace_ambiguous",
                "Agent has more than one active local workspace runtime binding",
            )
        if not candidates:
            return (
                0,
                False,
                canonical_sha256_digest(
                    {"agent_member_id": subject_member_id, "workspace_ready": False}
                ),
            )
        candidate = candidates[0]
        generation = candidate.payload.get("generation")
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
        ):
            raise KernelContractError(
                "public_projection_workspace_invalid",
                "Workspace runtime binding has an invalid generation",
            )
        ready = expected_generation == generation
        return generation, ready, candidate.record_digest


def _resident_workspace_projection(
    *,
    subject: KernelRecordSnapshot,
    intents: tuple[KernelRecordSnapshot, ...],
    generations: tuple[KernelRecordSnapshot, ...],
    runtime_bindings: tuple[KernelRecordSnapshot, ...],
    failures: tuple[KernelRecordSnapshot, ...],
    reconciliations: tuple[KernelRecordSnapshot, ...] = (),
) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    member_id = subject.payload.get("agent_member_id")
    generation = subject.payload.get("workspace_generation")
    if (
        not isinstance(member_id, str)
        or not member_id
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 1
    ):
        raise KernelContractError(
            "resident_teammate_state_incompatible",
            "Resident teammate lacks an exact current workspace generation",
            details={"fallback_performed": False},
        )
    intent_records = tuple(
        record
        for record in intents
        if record.payload.get("agent_member_id") == member_id
        and record.payload.get("generation") == generation
    )
    if len(intent_records) != 1:
        raise KernelContractError(
            "resident_teammate_state_incompatible",
            "Resident teammate must have one exact provisioning intent",
            details={
                "agent_member_id": member_id,
                "workspace_generation": generation,
                "matching_intent_count": len(intent_records),
                "fallback_performed": False,
            },
        )
    intent_record = intent_records[0]
    try:
        intent = WorkspaceProvisioningIntent.from_dict(
            _json_contract_payload(intent_record)
        )
    except (TypeError, ValueError) as exc:
        raise KernelContractError(
            "resident_teammate_state_incompatible",
            "Resident teammate provisioning intent violates its closed contract",
            details={
                "provisioning_intent_id": intent_record.entity_id,
                "fallback_performed": False,
            },
        ) from exc
    if (
        intent.intent_id != intent_record.entity_id
        or intent.state_version != intent_record.state_version
    ):
        raise KernelContractError(
            "resident_teammate_state_incompatible",
            "Provisioning intent identity differs from the resident teammate",
            details={
                "provisioning_intent_id": intent.intent_id,
                "fallback_performed": False,
            },
        )

    reconciliation_by_attempt: dict[int, WorkspaceProvisioningReconciliation] = {}
    for record in reconciliations:
        if record.payload.get("intent_id") != intent.intent_id:
            continue
        try:
            reconciliation = WorkspaceProvisioningReconciliation.from_dict(
                _json_contract_payload(record)
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "resident_teammate_state_incompatible",
                "Workspace provisioning reconciliation violates its closed contract",
                details={
                    "reconciliation_id": record.entity_id,
                    "fallback_performed": False,
                },
            ) from exc
        if (
            reconciliation.reconciliation_id != record.entity_id
            or reconciliation.state_version != record.state_version
            or reconciliation.session_id != intent.session_id
            or reconciliation.intent_id != intent.intent_id
            or reconciliation.blocked_intent_state_version != intent.state_version
            or reconciliation.blocked_intent_digest != intent.intent_digest
            or reconciliation.provision_request.intent_id != intent.intent_id
            or reconciliation.provision_request.session_id != intent.session_id
            or reconciliation.provision_request.agent_member_id
            != intent.agent_member_id
            or reconciliation.provision_request.workspace_id != intent.workspace_id
            or reconciliation.provision_request.generation != intent.generation
            or reconciliation.provision_request.repository_pin_digest
            != intent.repository_pin_digest
            or reconciliation.provision_request.provider_id != intent.provider_id
            or reconciliation.provision_request.target_id != intent.target_id
            or reconciliation.provision_request.adapter_binding_digest
            != intent.adapter_binding_digest
            or reconciliation.provision_request.controlled_operation_id
            != intent.controlled_operation_id
            or reconciliation.attempt in reconciliation_by_attempt
        ):
            raise KernelContractError(
                "resident_teammate_state_incompatible",
                "Workspace provisioning reconciliation differs from its failed source",
                details={
                    "reconciliation_id": reconciliation.reconciliation_id,
                    "fallback_performed": False,
                },
            )
        reconciliation_by_attempt[reconciliation.attempt] = reconciliation
    ordered_reconciliations = tuple(
        reconciliation_by_attempt[attempt]
        for attempt in sorted(reconciliation_by_attempt)
    )
    if ordered_reconciliations:
        if (
            intent.status is not WorkspaceProvisioningStatus.BLOCKED
            or intent.effect_certainty is None
            or intent.effect_certainty.value != "dispatch_in_doubt"
            or not intent.reconcile_required
            or tuple(item.attempt for item in ordered_reconciliations)
            != tuple(range(1, len(ordered_reconciliations) + 1))
        ):
            raise KernelContractError(
                "resident_teammate_state_incompatible",
                "Reconciliation lineage requires one exact dispatch-in-doubt blocker",
                details={
                    "provisioning_intent_id": intent.intent_id,
                    "fallback_performed": False,
                },
            )
        for index, reconciliation in enumerate(ordered_reconciliations):
            expected_parent = (
                None
                if index == 0
                else ordered_reconciliations[index - 1].reconciliation_id
            )
            if reconciliation.parent_reconciliation_id != expected_parent:
                raise KernelContractError(
                    "resident_teammate_state_incompatible",
                    "Workspace provisioning reconciliation lineage is discontinuous",
                    details={
                        "reconciliation_id": reconciliation.reconciliation_id,
                        "fallback_performed": False,
                    },
                )
            if index and (
                ordered_reconciliations[index - 1].status
                is not WorkspaceProvisioningReconciliationStatus.BLOCKED
                or not ordered_reconciliations[index - 1].reconcile_required
            ):
                raise KernelContractError(
                    "resident_teammate_state_incompatible",
                    "A successor observation follows a non-reconcilable occurrence",
                    details={
                        "reconciliation_id": reconciliation.reconciliation_id,
                        "fallback_performed": False,
                    },
                )
    current_reconciliation = (
        None if not ordered_reconciliations else ordered_reconciliations[-1]
    )

    generation_records = tuple(
        record
        for record in generations
        if record.entity_id == intent.workspace_id
        and record.payload.get("generation") == intent.generation
    )
    if len(generation_records) != 1:
        raise KernelContractError(
            "resident_teammate_state_incompatible",
            "Resident teammate must have one exact canonical workspace generation",
            details={
                "workspace_id": intent.workspace_id,
                "workspace_generation": intent.generation,
                "matching_generation_count": len(generation_records),
                "fallback_performed": False,
            },
        )
    generation_record = generation_records[0]
    try:
        canonical_generation = WorkspaceGeneration.from_dict(
            _json_contract_payload(generation_record)
        )
    except (TypeError, ValueError) as exc:
        raise KernelContractError(
            "resident_teammate_state_incompatible",
            "Resident teammate workspace generation violates its closed contract",
            details={
                "workspace_id": intent.workspace_id,
                "fallback_performed": False,
            },
        ) from exc
    if (
        canonical_generation.workspace_id != intent.workspace_id
        or canonical_generation.session_id != intent.session_id
        or canonical_generation.owner_member_id != intent.agent_member_id
        or canonical_generation.generation != intent.generation
        or canonical_generation.state_version != generation_record.state_version
    ):
        raise KernelContractError(
            "resident_teammate_state_incompatible",
            "Workspace generation identity differs from provisioning",
            details={
                "workspace_id": intent.workspace_id,
                "fallback_performed": False,
            },
        )

    binding_records = tuple(
        record
        for record in runtime_bindings
        if record.payload.get("owner_member_id") == member_id
        and record.payload.get("workspace_id") == intent.workspace_id
        and record.payload.get("generation") == generation
    )
    if len(binding_records) > 1:
        raise KernelContractError(
            "resident_teammate_state_incompatible",
            "Resident teammate has ambiguous runtime workspace bindings",
            details={
                "workspace_id": intent.workspace_id,
                "workspace_generation": generation,
                "fallback_performed": False,
            },
        )
    runtime_binding_id: str | None = None
    if binding_records:
        binding_record = binding_records[0]
        try:
            binding = WorkspaceRuntimeBinding.from_dict(
                _json_contract_payload(binding_record)
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "resident_teammate_state_incompatible",
                "Resident teammate runtime binding violates its closed contract",
                details={
                    "runtime_binding_id": binding_record.entity_id,
                    "fallback_performed": False,
                },
            ) from exc
        if (
            binding_record.entity_id != binding.workspace_id
            or binding.state_version != canonical_generation.state_version
            or binding.session_id != intent.session_id
            or binding.owner_member_id != intent.agent_member_id
            or binding.generation != intent.generation
            or binding.provider_id != canonical_generation.provider_id
            or binding.target_id != canonical_generation.target_id
            or binding.root_identity_digest != canonical_generation.root_identity_digest
        ):
            raise KernelContractError(
                "resident_teammate_state_incompatible",
                "Runtime workspace binding identity differs from provisioning",
                details={
                    "runtime_binding_id": binding_record.entity_id,
                    "fallback_performed": False,
                },
            )
        runtime_binding_id = binding_record.entity_id

    effective_ready = intent.status is WorkspaceProvisioningStatus.READY or (
        current_reconciliation is not None
        and current_reconciliation.status
        is WorkspaceProvisioningReconciliationStatus.READY
    )
    if effective_ready != (runtime_binding_id is not None):
        raise KernelContractError(
            "resident_teammate_state_incompatible",
            "Provisioning readiness and runtime workspace binding disagree",
            details={
                "provisioning_intent_id": intent.intent_id,
                "status": intent.status.value,
                "runtime_binding_present": runtime_binding_id is not None,
                "fallback_performed": False,
            },
        )

    failure: FailureObservation | None = None
    if intent.failure_id is not None:
        failure_records = tuple(
            record for record in failures if record.entity_id == intent.failure_id
        )
        if len(failure_records) != 1:
            raise KernelContractError(
                "resident_teammate_state_incompatible",
                "Blocked provisioning lacks its exact public failure observation",
                details={
                    "failure_id": intent.failure_id,
                    "fallback_performed": False,
                },
            )
        try:
            parsed_failure = parse_failure_observation(
                _json_contract_payload(failure_records[0])
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "resident_teammate_state_incompatible",
                "Provisioning failure violates the current public contract",
                details={
                    "failure_id": intent.failure_id,
                    "fallback_performed": False,
                },
            ) from exc
        if not isinstance(parsed_failure, FailureObservation):
            raise KernelContractError(
                "resident_teammate_state_incompatible",
                "Legacy failure evidence cannot represent current provisioning truth",
                details={
                    "failure_id": intent.failure_id,
                    "fallback_performed": False,
                },
            )
        failure = parsed_failure
        if (
            failure.failure_id != intent.failure_id
            or failure.session_id != intent.session_id
            or failure.diagnostic_id != intent.diagnostic_id
            or failure.effect_certainty is not intent.effect_certainty
            or failure.mutation_applied is not intent.mutation_applied
            or failure.fallback_performed != intent.fallback_performed
        ):
            raise KernelContractError(
                "resident_teammate_state_incompatible",
                "Provisioning intent and failure observation disagree",
                details={
                    "failure_id": intent.failure_id,
                    "fallback_performed": False,
                },
            )

    if current_reconciliation is None:
        next_action = {
            WorkspaceProvisioningStatus.PENDING: "wait_for_provisioning_worker",
            WorkspaceProvisioningStatus.CLAIMED: "wait_for_provisioning_worker",
            WorkspaceProvisioningStatus.READY: "message_or_drain",
            WorkspaceProvisioningStatus.BLOCKED: (
                "reconcile_workspace_provisioning"
                if intent.reconcile_required
                else "create_successor_workspace_generation"
            ),
            WorkspaceProvisioningStatus.CANCELLED: (
                "create_successor_workspace_generation"
            ),
        }[intent.status]
        readiness_state = {
            WorkspaceProvisioningStatus.PENDING: "provisioning",
            WorkspaceProvisioningStatus.CLAIMED: "provisioning",
            WorkspaceProvisioningStatus.READY: "ready",
            WorkspaceProvisioningStatus.BLOCKED: "blocked",
            WorkspaceProvisioningStatus.CANCELLED: "blocked",
        }[intent.status]
        current_failure_id = intent.failure_id
    else:
        next_action = {
            WorkspaceProvisioningReconciliationStatus.PENDING: (
                "wait_for_reconciliation_worker"
            ),
            WorkspaceProvisioningReconciliationStatus.CLAIMED: (
                "wait_for_reconciliation_worker"
            ),
            WorkspaceProvisioningReconciliationStatus.READY: "message_or_drain",
            WorkspaceProvisioningReconciliationStatus.BLOCKED: (
                "reconcile_workspace_provisioning"
                if current_reconciliation.reconcile_required
                else "create_successor_workspace_generation"
            ),
        }[current_reconciliation.status]
        readiness_state = "ready" if effective_ready else "blocked"
        current_failure_id = (
            current_reconciliation.failure_id
            if current_reconciliation.status
            is WorkspaceProvisioningReconciliationStatus.BLOCKED
            else (
                intent.failure_id
                if current_reconciliation.status
                in {
                    WorkspaceProvisioningReconciliationStatus.PENDING,
                    WorkspaceProvisioningReconciliationStatus.CLAIMED,
                }
                else None
            )
        )
    readiness: dict[str, JsonValue] = {
        "schema_version": "resident_teammate_readiness@1",
        "readiness": readiness_state,
        "workspace_id": intent.workspace_id,
        "workspace_generation": intent.generation,
        "provisioning_intent_id": intent.intent_id,
        "provisioning_intent_digest": intent.intent_digest,
        "failure_id": current_failure_id,
        "next_action": next_action,
    }
    provisioning: dict[str, JsonValue] = {
        "schema_version": "workspace_provisioning_public@2",
        "intent_id": intent.intent_id,
        "intent_digest": intent.intent_digest,
        "intent_state_version": intent.state_version,
        "status": intent.status.value,
        "workspace_id": intent.workspace_id,
        "workspace_generation": intent.generation,
        "runtime_binding_id": runtime_binding_id,
        "failure_id": intent.failure_id,
        "error_code": None if failure is None else failure.error_code,
        "effect_certainty": (
            None if intent.effect_certainty is None else intent.effect_certainty.value
        ),
        "mutation_applied": intent.mutation_applied,
        "fallback_performed": intent.fallback_performed,
        "retry_permitted": False,
        "reconcile_required": intent.reconcile_required,
        "diagnostic_id": intent.diagnostic_id,
        "next_action": next_action,
        "reconciliation": (
            None
            if current_reconciliation is None
            else {
                "schema_version": "workspace_provisioning_reconciliation_public@1",
                "reconciliation_id": current_reconciliation.reconciliation_id,
                "reconciliation_digest": (current_reconciliation.reconciliation_digest),
                "status": current_reconciliation.status.value,
                "attempt": current_reconciliation.attempt,
                "parent_reconciliation_id": (
                    current_reconciliation.parent_reconciliation_id
                ),
                "blocked_intent_state_version": (
                    current_reconciliation.blocked_intent_state_version
                ),
                "blocked_intent_digest": (current_reconciliation.blocked_intent_digest),
                "source_receipt_id": current_reconciliation.source_receipt_id,
                "source_receipt_digest": (current_reconciliation.source_receipt_digest),
                "dispatch_receipt_digest": (
                    current_reconciliation.dispatch_receipt_digest
                ),
                "result_receipt_id": current_reconciliation.result_receipt_id,
                "result_receipt_digest": (current_reconciliation.result_receipt_digest),
                "effect_certainty": (
                    None
                    if current_reconciliation.effect_certainty is None
                    else current_reconciliation.effect_certainty.value
                ),
                "mutation_applied": current_reconciliation.mutation_applied,
                "fallback_performed": current_reconciliation.fallback_performed,
                "retry_permitted": False,
                "reconcile_required": current_reconciliation.reconcile_required,
                "failure_id": current_reconciliation.failure_id,
                "diagnostic_id": current_reconciliation.diagnostic_id,
                "requested_at": current_reconciliation.requested_at,
                "requested_claim_seconds": (
                    current_reconciliation.requested_claim_seconds
                ),
                "settled_at": current_reconciliation.settled_at,
                "next_action": next_action,
            }
        ),
    }
    return readiness, provisioning


def _ordered_transcript_projection(
    *,
    messages: tuple[KernelRecordSnapshot, ...],
    outcomes: tuple[KernelRecordSnapshot, ...],
) -> dict[str, JsonValue]:
    outcome_messages: dict[str, tuple[object, object, int, str]] = {}
    for record in outcomes:
        try:
            receipt = RuntimeTurnOutcomeReceipt.from_dict(
                _json_contract_payload(record)
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "resident_transcript_outcome_invalid",
                "Runtime outcome receipt violates its closed contract",
                details={
                    "outcome_receipt_id": record.entity_id,
                    "fallback_performed": False,
                },
            ) from exc
        if receipt.receipt_id != record.entity_id:
            raise KernelContractError(
                "resident_transcript_outcome_identity_drift",
                "Runtime outcome receipt differs from its record identity",
                details={
                    "outcome_receipt_id": record.entity_id,
                    "fallback_performed": False,
                },
            )
        for position, message in enumerate(receipt.outcome.messages):
            if message.message_id in outcome_messages:
                raise KernelContractError(
                    "resident_transcript_message_identity_collision",
                    "Runtime outcomes reuse one conversation message identity",
                    details={
                        "message_id": message.message_id,
                        "fallback_performed": False,
                    },
                )
            outcome_messages[message.message_id] = (
                receipt.outcome,
                message,
                position,
                receipt.accepted_at,
            )

    sortable: list[tuple[tuple[object, ...], dict[str, JsonValue]]] = []
    observed_message_ids: set[str] = set()
    for record in messages:
        payload = record.payload
        message_id = payload.get("message_id")
        role = payload.get("sender_kind")
        content = payload.get("content")
        created_at = payload.get("created_at")
        correlation_id = payload.get("correlation_id")
        if (
            not isinstance(message_id, str)
            or not message_id
            or message_id != record.entity_id
            or message_id in observed_message_ids
            or role not in {"user", "assistant", "tool"}
            or not isinstance(content, str)
            or not content
            or not isinstance(created_at, str)
            or not created_at
            or (correlation_id is not None and not isinstance(correlation_id, str))
        ):
            raise KernelContractError(
                "resident_transcript_message_invalid",
                "Conversation message cannot enter the current ordered transcript",
                details={
                    "message_id": record.entity_id,
                    "fallback_performed": False,
                },
            )
        observed_message_ids.add(message_id)
        source_command_id: str | None = None
        source_outcome_id: str | None = None
        tool_call_id: str | None = None
        causal_key: tuple[object, ...]
        outcome_source = outcome_messages.pop(message_id, None)
        if role == "user":
            if outcome_source is not None:
                raise KernelContractError(
                    "resident_transcript_source_drift",
                    "User message is incorrectly owned by a runtime outcome",
                    details={
                        "message_id": message_id,
                        "fallback_performed": False,
                    },
                )
            causal_key = (created_at, 0, message_id)
        else:
            if outcome_source is None:
                raise KernelContractError(
                    "resident_transcript_source_missing",
                    "Assistant or tool message lacks its exact runtime outcome",
                    details={
                        "message_id": message_id,
                        "fallback_performed": False,
                    },
                )
            outcome, runtime_message, position, accepted_at = outcome_source
            if (
                runtime_message.role.value != role
                or runtime_message.content != content
                or created_at != accepted_at
                or correlation_id
                != (runtime_message.correlation_id or outcome.correlation_id)
            ):
                raise KernelContractError(
                    "resident_transcript_source_drift",
                    "Conversation message differs from its atomic runtime outcome",
                    details={
                        "message_id": message_id,
                        "fallback_performed": False,
                    },
                )
            source_command_id = outcome.command_id
            source_outcome_id = outcome.outcome_id
            tool_call_id = runtime_message.tool_call_id
            causal_key = (
                created_at,
                1,
                outcome.command_id,
                outcome.outcome_id,
                position,
                message_id,
            )
        sortable.append(
            (
                causal_key,
                {
                    "schema_version": "resident_transcript_message@1",
                    "ordinal": 0,
                    "message_id": message_id,
                    "role": role,
                    "content": (
                        _public_tool_transcript_content(content)
                        if role == "tool"
                        else content
                    ),
                    "correlation_id": correlation_id,
                    "tool_call_id": tool_call_id,
                    "source_command_id": source_command_id,
                    "source_outcome_id": source_outcome_id,
                    "created_at": created_at,
                },
            )
        )
    if outcome_messages:
        raise KernelContractError(
            "resident_transcript_message_missing",
            "Runtime outcome messages are absent from the canonical conversation",
            details={
                "message_ids": sorted(outcome_messages),
                "fallback_performed": False,
            },
        )
    ordered: list[dict[str, JsonValue]] = []
    for ordinal, (_, payload) in enumerate(
        sorted(sortable, key=lambda item: item[0]), 1
    ):
        payload["ordinal"] = ordinal
        ordered.append(payload)
    transcript: dict[str, JsonValue] = {
        "schema_version": "ordered_transcript@1",
        "messages": ordered,
    }
    transcript["transcript_digest"] = canonical_sha256_digest(transcript)
    return transcript


def _contract_payloads(
    records: tuple[KernelRecordSnapshot, ...],
) -> list[JsonValue]:
    """Expose closed contract payloads without injecting Store CAS metadata."""

    return [_json_contract_payload(record) for record in records]


_RUNTIME_SIGNAL_PUBLIC_FIELDS = (
    "signal_id",
    "session_id",
    "agent_id",
    "agent_member_id",
    "reason",
    "status",
    "created_at",
    "task_id",
    "lane_id",
    "correlation_id",
    "source_ref",
    "claimed_at",
    "claimed_by",
    "claim_expires_at",
    "attempt_count",
    "completed_at",
    "session_fencing_token",
    "runtime_lease_generation",
    "capability_lease_id",
    "workspace_generation",
    "process_epoch",
    "enqueue_command_digest",
    "claim_command_digest",
)
_SESSION_RUNTIME_LEASE_PUBLIC_FIELDS = (
    "session_id",
    "owner_id",
    "mode",
    "acquired_at",
    "heartbeat_at",
    "expires_at",
    "fencing_token",
    "released_at",
    "acquire_command_digest",
)


def _selected_record_payload(
    record: KernelRecordSnapshot,
    *,
    fields: tuple[str, ...],
) -> dict[str, JsonValue]:
    source = _json_contract_payload(record)
    payload = {name: source[name] for name in fields if name in source}
    payload["state_version"] = record.state_version
    return payload


def _runtime_signal_public(
    records: tuple[KernelRecordSnapshot, ...],
) -> list[JsonValue]:
    return [
        _selected_record_payload(record, fields=_RUNTIME_SIGNAL_PUBLIC_FIELDS)
        for record in records
    ]


def _session_runtime_lease_public(
    records: tuple[KernelRecordSnapshot, ...],
) -> list[JsonValue]:
    return [
        _selected_record_payload(
            record,
            fields=_SESSION_RUNTIME_LEASE_PUBLIC_FIELDS,
        )
        for record in records
    ]


def _runtime_commands_public(
    records: tuple[KernelRecordSnapshot, ...],
    *,
    failures: tuple[KernelRecordSnapshot, ...] = (),
) -> list[JsonValue]:
    failure_by_id = {record.entity_id: record for record in failures}
    if len(failure_by_id) != len(failures):
        raise KernelContractError(
            "public_projection_failure_identity_collision",
            "Runtime command failure projection contains duplicate identities",
            details={"fallback_performed": False},
        )
    public_records: list[JsonValue] = []
    for record in records:
        source = _json_contract_payload(record)
        expected = {
            "schema_version",
            "command_id",
            "session_id",
            "command_type",
            "request_digest",
            "idempotency_key",
            "status",
            "max_signals",
            "max_steps_per_agent",
            "auto_enqueue_ready_tasks",
            "state_version",
            "fencing_token",
            "accepted_at",
            "claim_owner",
            "lease_token",
            "lease_expires_at",
            "bounded_outcome_summary",
            "failure_id",
            "diagnostic_id",
            "error_code",
            "safe_error_summary",
            "safe_retry_hint",
            "started_at",
            "completed_at",
        }
        if (
            set(source) != expected
            or source.get("schema_version") != "runtime_command@1"
            or source.get("command_id") != record.entity_id
            or source.get("state_version") != record.state_version
        ):
            raise KernelContractError(
                "public_projection_runtime_command_invalid",
                "Stored runtime command violates its closed source contract",
                details={
                    "runtime_command_id": record.entity_id,
                    "fallback_performed": False,
                },
            )
        failure_id = source.get("failure_id")
        diagnostic_id = source.get("diagnostic_id")
        if source.get("status") == "failed":
            failure_record = (
                None
                if not isinstance(failure_id, str)
                else failure_by_id.get(failure_id)
            )
            try:
                failure = (
                    None
                    if failure_record is None
                    else parse_failure_observation(
                        _json_contract_payload(failure_record)
                    )
                )
            except (TypeError, ValueError) as exc:
                raise KernelContractError(
                    "public_projection_runtime_command_failure_invalid",
                    "Failed runtime command references an invalid failure observation",
                    details={
                        "runtime_command_id": record.entity_id,
                        "failure_id": failure_id,
                        "fallback_performed": False,
                    },
                ) from exc
            if not isinstance(failure, FailureObservation) or (
                not isinstance(diagnostic_id, str)
                or failure.session_id != source.get("session_id")
                or failure.source_kind != "runtime_command"
                or failure.source_ref != record.entity_id
                or failure.failure_id != failure_id
                or failure.diagnostic_id != diagnostic_id
            ):
                raise KernelContractError(
                    "public_projection_runtime_command_failure_unresolved",
                    "Failed runtime command does not resolve its exact public failure",
                    details={
                        "runtime_command_id": record.entity_id,
                        "failure_id": failure_id,
                        "fallback_performed": False,
                    },
                )
        elif failure_id is not None or diagnostic_id is not None:
            raise KernelContractError(
                "public_projection_runtime_command_failure_unexpected",
                "Non-failed runtime command carries failure identities",
                details={
                    "runtime_command_id": record.entity_id,
                    "fallback_performed": False,
                },
            )
        payload = dict(source)
        payload["schema_version"] = "runtime_command_public@1"
        payload.pop("lease_token")
        payload["bounded_outcome_summary"] = _runtime_command_outcome_summary_public(
            payload["bounded_outcome_summary"],
            runtime_command_id=record.entity_id,
        )
        public_records.append(payload)
    return public_records


def _runtime_command_outcome_summary_public(
    value: object,
    *,
    runtime_command_id: str,
) -> JsonValue:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise KernelContractError(
            "public_projection_runtime_command_summary_invalid",
            "Stored runtime command outcome summary is not an object",
            details={
                "runtime_command_id": runtime_command_id,
                "fallback_performed": False,
            },
        )
    processed_signals = value.get("processed_signals")
    runtime_executed = value.get("runtime_executed")
    task_transition_performed = value.get("task_transition_performed")
    fallback_performed = value.get("fallback_performed")
    turns = value.get("turns")
    if turns is None and processed_signals == 0:
        turns = []
    if (
        not isinstance(processed_signals, int)
        or isinstance(processed_signals, bool)
        or not 0 <= processed_signals <= 1_024
        or not isinstance(runtime_executed, bool)
        or runtime_executed != (processed_signals > 0)
        or not isinstance(task_transition_performed, bool)
        or fallback_performed is not False
        or not isinstance(turns, (list, tuple))
        or len(turns) != processed_signals
    ):
        raise KernelContractError(
            "public_projection_runtime_command_summary_invalid",
            "Stored runtime command outcome summary violates its safe public contract",
            details={
                "runtime_command_id": runtime_command_id,
                "fallback_performed": False,
            },
        )
    return {
        "schema_version": "runtime_command_outcome_summary_public@1",
        "processed_signals": processed_signals,
        "turn_count": len(turns),
        "turns_digest": canonical_sha256_digest(turns),
        "runtime_executed": runtime_executed,
        "task_transition_performed": task_transition_performed,
        "fallback_performed": False,
    }


def _runtime_turn_commands_public(
    records: tuple[KernelRecordSnapshot, ...],
) -> list[JsonValue]:
    public_records: list[JsonValue] = []
    for record in records:
        try:
            command = RuntimeTurnCommand.from_dict(_json_contract_payload(record))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "public_projection_runtime_turn_command_invalid",
                "Stored runtime turn command violates its closed source contract",
                details={
                    "runtime_turn_command_id": record.entity_id,
                    "fallback_performed": False,
                },
            ) from exc
        if command.command_id != record.entity_id:
            raise KernelContractError(
                "public_projection_runtime_turn_command_identity_drift",
                "Stored runtime turn command differs from its record identity",
                details={
                    "runtime_turn_command_id": record.entity_id,
                    "fallback_performed": False,
                },
            )
        public_records.append(
            {
                "schema_version": "runtime_turn_command_public@1",
                "command_id": command.command_id,
                "turn_id": command.turn_id,
                "session_id": command.session_id,
                "agent_id": command.agent_id,
                "agent_member_id": command.agent_member_id,
                "signal_id": command.signal_id,
                "signal_attempt": command.signal_attempt,
                "runtime_lease_generation": command.runtime_lease_generation,
                "runtime_fence": command.runtime_fence,
                "process_epoch": command.process_epoch,
                "distribution_id": command.distribution_id,
                "distribution_manifest_digest": (command.distribution_manifest_digest),
                "release_digest": command.release_digest,
                "adapter_bundle_digest": command.adapter_bundle_digest,
                "extension_bundle_digest": command.extension_bundle_digest,
                "declared_tool_catalog_digest": (command.declared_tool_catalog_digest),
                "capability_binding_id": command.capability_binding_id,
                "capability_binding_revision": command.capability_binding_revision,
                "capability_binding_digest": command.capability_binding_digest,
                "affordance_snapshot_id": command.affordance_snapshot_id,
                "affordance_snapshot_digest": command.affordance_snapshot_digest,
                "workflow_authority_id": command.workflow_authority_id,
                "workflow_authority_epoch": command.workflow_authority_epoch,
                "workflow_authority_digest": command.workflow_authority_digest,
                "signal_authority_link_digest": (command.signal_authority_link_digest),
                "tool_exposure_snapshot_id": command.tool_exposure_snapshot_id,
                "tool_exposure_snapshot_digest": (
                    command.tool_exposure_snapshot_digest
                ),
                "context_digest": command.context.context_digest,
                "message_count": len(command.messages),
                "runtime_adapter_id": command.runtime_adapter_id,
                "runtime_adapter_contract_digest": (
                    command.runtime_adapter_contract_digest
                ),
                "max_steps": command.max_steps,
                "max_duration_seconds": command.max_duration_seconds,
                "max_input_units": command.max_input_units,
                "max_output_units": command.max_output_units,
                "task_id": command.task_id,
                "lane_id": command.lane_id,
                "continuation_id": command.continuation_id,
                "source_command_digest": command.command_digest,
            }
        )
    return public_records


def _runtime_outcomes_public(
    records: tuple[KernelRecordSnapshot, ...],
) -> list[JsonValue]:
    public_records: list[JsonValue] = []
    for record in records:
        try:
            receipt = RuntimeTurnOutcomeReceipt.from_dict(
                _json_contract_payload(record)
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "public_projection_runtime_outcome_invalid",
                "Stored runtime outcome violates its closed source contract",
                details={
                    "runtime_outcome_receipt_id": record.entity_id,
                    "fallback_performed": False,
                },
            ) from exc
        if receipt.receipt_id != record.entity_id:
            raise KernelContractError(
                "public_projection_runtime_outcome_identity_drift",
                "Stored runtime outcome differs from its record identity",
                details={
                    "runtime_outcome_receipt_id": record.entity_id,
                    "fallback_performed": False,
                },
            )
        outcome = receipt.outcome
        failure = outcome.failure
        public_failure: JsonValue = None
        if failure is not None:
            public_failure = {
                "schema_version": "runtime_failure_public@1",
                "failure_id": failure.failure_id,
                "error_code": failure.error_code,
                "safe_summary": failure.safe_summary,
                "diagnostic_id": failure.diagnostic_id,
                "effect_certainty": failure.effect_certainty.value,
                "mutation_applied": failure.mutation_applied,
                "fallback_performed": failure.fallback_performed,
                "reconcile_required": (
                    failure.effect_certainty.value == "dispatch_in_doubt"
                ),
                "next_action": failure.next_action,
            }
        tool_request_payloads = [request.to_dict() for request in outcome.tool_requests]
        public_outcome: dict[str, JsonValue] = {
            "schema_version": "runtime_turn_outcome_public@1",
            "outcome_id": outcome.outcome_id,
            "command_id": outcome.command_id,
            "source_command_digest": outcome.command_digest,
            "turn_id": outcome.turn_id,
            "session_id": outcome.session_id,
            "agent_id": outcome.agent_id,
            "agent_member_id": outcome.agent_member_id,
            "signal_id": outcome.signal_id,
            "signal_attempt": outcome.signal_attempt,
            "runtime_lease_generation": outcome.runtime_lease_generation,
            "runtime_fence": outcome.runtime_fence,
            "process_epoch": outcome.process_epoch,
            "workflow_authority_id": outcome.workflow_authority_id,
            "workflow_authority_epoch": outcome.workflow_authority_epoch,
            "workflow_authority_digest": outcome.workflow_authority_digest,
            "tool_exposure_snapshot_id": outcome.tool_exposure_snapshot_id,
            "tool_exposure_snapshot_digest": (outcome.tool_exposure_snapshot_digest),
            "disposition": outcome.disposition.value,
            "summary": outcome.summary,
            "message_count": len(outcome.messages),
            "tool_request_count": len(outcome.tool_requests),
            "tool_request_digest": canonical_sha256_digest(tool_request_payloads),
            "usage": None if outcome.usage is None else outcome.usage.to_dict(),
            "continuation_id": outcome.continuation_id,
            "waiting_approval_id": outcome.waiting_approval_id,
            "failure": public_failure,
            "task_id": outcome.task_id,
            "lane_id": outcome.lane_id,
            "correlation_id": outcome.correlation_id,
            "source_outcome_digest": outcome.outcome_digest,
        }
        public_records.append(
            {
                "schema_version": "runtime_turn_outcome_receipt_public@1",
                "receipt_id": receipt.receipt_id,
                "outcome": public_outcome,
                "accepted_at": receipt.accepted_at,
                "source_receipt_digest": receipt.receipt_digest,
            }
        )
    return public_records


def _json_contract_payload(record: KernelRecordSnapshot) -> dict[str, JsonValue]:
    payload = json_compatible(record.payload)
    if not isinstance(payload, dict):
        raise KernelContractError(
            "public_projection_contract_payload_invalid",
            "Stored contract payload is not a JSON object",
            details={
                "entity_type": record.entity_type,
                "entity_id": record.entity_id,
                "fallback_performed": False,
            },
        )
    return payload


def _payloads(records: tuple[KernelRecordSnapshot, ...]) -> list[JsonValue]:
    return [_public_record_payload(item) for item in records]


def _runtime_outcome_consumptions_public(
    records: tuple[KernelRecordSnapshot, ...],
) -> list[JsonValue]:
    payloads: list[JsonValue] = []
    expected_fields = {
        "schema_version",
        "consumption_id",
        "consumption_digest",
        "command_id",
        "command_digest",
        "outcome_id",
        "outcome_digest",
        "outcome_receipt",
        "session_id",
        "agent_id",
        "agent_member_id",
        "signal_id",
        "signal_attempt",
        "continuation_intent",
        "settlement_intent",
        "consumed_at",
    }
    for record in records:
        payload = _json_contract_payload(record)
        if set(payload) != expected_fields or payload.get("schema_version") != (
            "runtime_outcome_consumption@2"
        ):
            raise KernelContractError(
                "public_runtime_outcome_consumption_invalid",
                "Stored runtime outcome consumption violates its closed contract",
                details={
                    "consumption_record_id": record.entity_id,
                    "fallback_performed": False,
                },
            )
        receipt_payload = payload["outcome_receipt"]
        if not isinstance(receipt_payload, Mapping):
            raise KernelContractError(
                "public_runtime_outcome_consumption_invalid",
                "Stored runtime outcome consumption receipt is not structured",
            )
        try:
            receipt = RuntimeTurnOutcomeReceipt.from_dict(receipt_payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "public_runtime_outcome_consumption_invalid",
                "Stored runtime outcome consumption receipt is invalid",
            ) from exc
        continuation = payload["continuation_intent"]
        settlement = payload["settlement_intent"]
        if continuation is not None and not isinstance(continuation, Mapping):
            raise KernelContractError(
                "public_runtime_outcome_consumption_invalid",
                "Stored runtime continuation intent is not structured",
            )
        if not isinstance(settlement, Mapping):
            raise KernelContractError(
                "public_runtime_outcome_consumption_invalid",
                "Stored runtime settlement intent is not structured",
            )
        command_id = str(payload["command_id"])
        outcome_id = str(payload["outcome_id"])
        expected_consumption_digest = canonical_sha256_digest(
            {
                key: value
                for key, value in payload.items()
                if key != "consumption_digest"
            }
        )
        if (
            record.entity_id != command_id
            or payload["consumption_digest"] != expected_consumption_digest
            or receipt.outcome.command_id != command_id
            or receipt.outcome.outcome_id != outcome_id
            or receipt.outcome.command_digest != payload["command_digest"]
            or receipt.outcome.outcome_digest != payload["outcome_digest"]
            or receipt.outcome.session_id != payload["session_id"]
            or receipt.outcome.agent_id != payload["agent_id"]
            or receipt.outcome.agent_member_id != payload["agent_member_id"]
            or receipt.outcome.signal_id != payload["signal_id"]
            or receipt.outcome.signal_attempt != payload["signal_attempt"]
            or settlement.get("source_command_id") != command_id
            or settlement.get("source_outcome_id") != outcome_id
            or settlement.get("source_command_digest") != payload["command_digest"]
            or settlement.get("source_outcome_digest") != payload["outcome_digest"]
            or settlement.get("session_id") != payload["session_id"]
            or settlement.get("agent_id") != payload["agent_id"]
            or settlement.get("agent_member_id") != payload["agent_member_id"]
            or settlement.get("signal_id") != payload["signal_id"]
            or settlement.get("signal_attempt") != payload["signal_attempt"]
            or (
                continuation is not None
                and (
                    continuation.get("source_command_id") != command_id
                    or continuation.get("source_outcome_id") != outcome_id
                    or continuation.get("source_command_digest")
                    != payload["command_digest"]
                    or continuation.get("source_outcome_digest")
                    != payload["outcome_digest"]
                    or continuation.get("session_id") != payload["session_id"]
                    or continuation.get("agent_id") != payload["agent_id"]
                    or continuation.get("agent_member_id") != payload["agent_member_id"]
                )
            )
        ):
            raise KernelContractError(
                "public_runtime_outcome_consumption_identity_drift",
                "Stored runtime outcome consumption identities differ",
                details={"command_id": command_id, "fallback_performed": False},
            )
        public = {
            "schema_version": RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_SCHEMA_VERSION,
            "consumption_id": payload["consumption_id"],
            "consumption_digest": payload["consumption_digest"],
            "command_id": command_id,
            "command_digest": payload["command_digest"],
            "outcome_id": outcome_id,
            "outcome_digest": payload["outcome_digest"],
            "outcome_receipt_id": receipt.receipt_id,
            "outcome_receipt_digest": receipt.receipt_digest,
            "session_id": payload["session_id"],
            "agent_id": payload["agent_id"],
            "agent_member_id": payload["agent_member_id"],
            "signal_id": payload["signal_id"],
            "signal_attempt": payload["signal_attempt"],
            "continuation_intent_id": (
                None if continuation is None else continuation.get("continuation_id")
            ),
            "settlement_intent_id": settlement.get("settlement_id"),
            "consumed_at": payload["consumed_at"],
        }
        payloads.append(json_compatible(public))
    return payloads


def _public_failure_payloads(
    records: tuple[KernelRecordSnapshot, ...],
) -> list[JsonValue]:
    payloads: list[JsonValue] = []
    for record in records:
        try:
            failure = parse_failure_observation(_json_contract_payload(record))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "public_projection_failure_invalid",
                "Stored failure observation violates its closed current contract",
                details={
                    "failure_id": record.entity_id,
                    "fallback_performed": False,
                },
            ) from exc
        if not isinstance(failure, FailureObservation):
            raise KernelContractError(
                "resident_teammate_state_incompatible",
                "Legacy failure observations cannot enter the resident public projection",
                details={
                    "failure_id": record.entity_id,
                    "fallback_performed": False,
                },
            )
        if failure.failure_id != record.entity_id:
            raise KernelContractError(
                "public_projection_failure_identity_drift",
                "Stored failure observation differs from its record identity",
                details={
                    "failure_id": record.entity_id,
                    "fallback_performed": False,
                },
            )
        payload = failure.to_dict()
        payload["facts"] = _public_failure_mapping(
            failure.facts,
            allowed_fields=FILE_WORKSPACE_FAILURE_FACT_PUBLIC_FIELDS,
        )
        payload["identities"] = _public_failure_mapping(
            failure.identities or {},
            allowed_fields=FILE_WORKSPACE_FAILURE_IDENTITY_PUBLIC_FIELDS,
        )
        payloads.append(json_compatible(payload))
    return payloads


def _public_failure_mapping(
    value: Mapping[str, object],
    *,
    allowed_fields: frozenset[str],
) -> dict[str, JsonValue]:
    public: dict[str, JsonValue] = {}
    for key in sorted(value):
        if key not in allowed_fields:
            continue
        safe = _public_failure_value(value[key])
        if safe is not None:
            public[key] = safe
    return public


def _public_failure_value(value: object) -> JsonValue | None:
    if isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        if not value or len(value) > 512 or value.startswith(("/", "\\")):
            return None
        return value
    if isinstance(value, (list, tuple)) and len(value) <= 64:
        items = [_public_failure_value(item) for item in value]
        if any(item is None for item in items):
            return None
        return [item for item in items if item is not None]
    return None


def _public_conversation_payloads(
    records: tuple[KernelRecordSnapshot, ...],
) -> list[JsonValue]:
    payloads: list[JsonValue] = []
    for record in records:
        payload = _public_record_payload(record)
        if payload.get("sender_kind") == "tool":
            content = payload.get("content")
            if not isinstance(content, str):
                raise KernelContractError(
                    "public_projection_tool_message_invalid",
                    "Stored tool transcript content must be a string",
                    details={
                        "message_id": record.entity_id,
                        "fallback_performed": False,
                    },
                )
            payload["content"] = _public_tool_transcript_content(content)
        payloads.append(payload)
    return payloads


def _public_tool_transcript_content(content: str) -> str:
    """Reduce an internal ToolResult to explicit public-safe settlement facts."""

    try:
        value = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "Tool result recorded; inspect its public runtime summary."
    if not isinstance(value, dict):
        return "Tool result recorded; inspect its public runtime summary."
    public: dict[str, JsonValue] = {
        "schema_version": "tool_result_public@1",
        "call_id": value.get("call_id"),
        "ok": value.get("ok"),
        "status": value.get("status"),
        "summary": value.get("summary"),
        "error_code": value.get("error_code"),
        "hint": value.get("hint"),
    }
    effect = value.get("payload")
    if isinstance(effect, dict):
        public["effect"] = {
            key: effect.get(key)
            for key in (
                "effect_certainty",
                "mutation_applied",
                "fallback_performed",
                "retry_performed",
                "reconcile_required",
                "diagnostic_id",
                "task_transition_performed",
                "authority_widened",
                "route_changed",
                "command_scope_expansion_applied",
            )
            if key in effect
        }
    else:
        public["effect"] = None
    return json.dumps(public, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalized_public_field(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _sanitize_public_value(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        sanitized: dict[str, JsonValue] = {}
        for key, nested in value.items():
            token = _normalized_public_field(key)
            if token in _FORBIDDEN_PUBLIC_FIELD_TOKENS or any(
                _normalized_public_field(fragment) in token
                for fragment in _FORBIDDEN_PUBLIC_FIELD_FRAGMENTS
            ):
                continue
            sanitized[str(key)] = _sanitize_public_value(nested)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_public_value(item) for item in value]
    return json_compatible(value)


def _public_record_payload(record: KernelRecordSnapshot) -> dict[str, JsonValue]:
    """Expose the canonical CAS version without leaking Store mechanics."""

    payload = dict(record.payload)
    if "state_version" in payload:
        if record.entity_type not in {
            "workspace_generation",
            "workspace_runtime_binding",
        }:
            raise KernelContractError(
                "public_projection_state_version_collision",
                "Canonical payload collides with the public state_version field",
            )
        payload["workspace_state_version"] = payload.pop("state_version")
    payload["state_version"] = record.state_version
    sanitized = _sanitize_public_value(payload)
    if not isinstance(sanitized, dict):
        raise KernelContractError(
            "public_projection_record_payload_invalid",
            "Public record payload is not a JSON object",
            details={
                "entity_type": record.entity_type,
                "entity_id": record.entity_id,
                "fallback_performed": False,
            },
        )
    return sanitized


def _lease_is_temporally_current(
    lease: AgentAuthorityLease,
    *,
    observed_at: str,
) -> bool:
    if lease.expires_at is None:
        return True
    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    expires = datetime.fromisoformat(lease.expires_at.replace("Z", "+00:00"))
    return observed < expires


def _projection_fact_time(
    *,
    binding: SessionCapabilityBindingRevision,
    lease: AgentAuthorityLease,
    subject_payload: Mapping[str, JsonValue],
) -> str:
    candidates = (
        binding.created_at,
        lease.updated_at,
        subject_payload.get("updated_at"),
    )
    return max(value for value in candidates if isinstance(value, str))


def build_public_tool_reflection(
    *,
    declared_catalog: DeclaredToolCatalog,
    affordance_snapshot: ToolAffordanceSnapshot,
) -> FileWorkspaceToolReflection:
    if (
        affordance_snapshot.declared_tool_catalog_digest
        != declared_catalog.catalog_digest
    ):
        raise KernelContractError(
            "public_tool_reflection_catalog_drift",
            "tool affordance snapshot belongs to another declared catalog",
        )
    declared_names = {entry.contract.tool_name for entry in declared_catalog.entries}
    observed_names = {item.tool_name for item in affordance_snapshot.affordances}
    if observed_names != declared_names:
        raise KernelContractError(
            "public_tool_reflection_incomplete",
            "tool affordance snapshot must classify every declared tool exactly once",
            details={
                "missing": sorted(declared_names - observed_names),
                "unexpected": sorted(observed_names - declared_names),
            },
        )
    return FileWorkspaceToolReflection(
        declared_tool_catalog_digest=declared_catalog.catalog_digest,
        affordance_snapshot=affordance_snapshot,
    )


def assemble_file_workspace_public_v2(
    *,
    release: LayeredReleaseIdentity,
    core_payload: Mapping[str, JsonValue],
    query_context: KernelQueryContext,
    projection_contributors: tuple[ProjectionContributor, ...],
    authorized_projection_contracts: Mapping[str, str],
    cursors: Mapping[str, str] | None = None,
    max_items_per_section: int = DEFAULT_EXTENSION_SECTION_MAX_ITEMS,
    max_bytes_per_section: int = DEFAULT_EXTENSION_SECTION_MAX_BYTES,
    max_total_bytes: int = DEFAULT_PUBLIC_PROJECTION_MAX_BYTES,
) -> FileWorkspacePublicV2:
    try:
        core_projection = FileWorkspaceCoreProjectionV2(core_payload)
    except ValueError as exc:
        raise KernelContractError(
            "public_core_projection_schema_invalid",
            str(exc),
        ) from exc
    if not 1 <= max_items_per_section <= 1_000:
        raise ValueError("max_items_per_section must be between 1 and 1000")
    if not 1 <= max_bytes_per_section <= 1_048_576:
        raise ValueError("max_bytes_per_section must be between 1 and 1048576")
    if not 1 <= max_total_bytes <= 16 * 1024 * 1024:
        raise ValueError("max_total_bytes must be between 1 and 16777216")

    contributors: dict[str, ProjectionContributor] = {}
    for contributor in projection_contributors:
        if contributor.section_id in contributors:
            raise KernelContractError(
                "public_extension_projection_collision",
                "two projection runtimes own the same public section",
                details={"section_id": contributor.section_id},
            )
        contributors[contributor.section_id] = contributor
    if set(contributors) != set(authorized_projection_contracts):
        raise KernelContractError(
            "public_extension_projection_mount_drift",
            "mounted projection runtimes differ from the authorized catalog",
            details={
                "missing": sorted(
                    set(authorized_projection_contracts) - set(contributors)
                ),
                "unexpected": sorted(
                    set(contributors) - set(authorized_projection_contracts)
                ),
            },
        )

    cursor_map = {} if cursors is None else dict(cursors)
    unknown_cursors = sorted(set(cursor_map) - set(contributors))
    if unknown_cursors:
        raise KernelContractError(
            "public_extension_projection_cursor_unknown",
            "cursor was supplied for an unavailable extension section",
            details={"section_ids": unknown_cursors},
        )

    sections: list[FileWorkspaceExtensionSectionV2] = []
    for section_id, contributor in sorted(contributors.items()):
        expected_digest = authorized_projection_contracts[section_id]
        if contributor.section_contract_digest != expected_digest:
            raise KernelContractError(
                "public_extension_projection_contract_drift",
                "projection runtime differs from the authorized section contract",
                details={"section_id": section_id},
            )
        result = contributor.project(
            ProjectionRequest(
                context=query_context,
                section_id=section_id,
                max_items=max_items_per_section,
                max_bytes=max_bytes_per_section,
                cursor=cursor_map.get(section_id),
            )
        )
        if (
            result.section_id != section_id
            or result.section_contract_digest != expected_digest
        ):
            raise KernelContractError(
                "public_extension_projection_result_drift",
                "projection result identity differs from the mounted runtime",
                details={"section_id": section_id},
            )
        _reject_private_projection_fields(
            result.payload, path=f"extensions.{section_id}"
        )
        encoded = _json_bytes(result.payload)
        if len(encoded) > max_bytes_per_section:
            raise KernelContractError(
                "public_extension_projection_budget_exceeded",
                "extension projection exceeded its declared byte budget",
                details={"section_id": section_id, "observed_bytes": len(encoded)},
            )
        sections.append(
            FileWorkspaceExtensionSectionV2(
                section_id=section_id,
                section_contract_digest=result.section_contract_digest,
                payload=result.payload,
                next_cursor=result.next_cursor,
                projection_digest=result.projection_digest,
            )
        )

    projection = FileWorkspacePublicV2(
        release=release,
        core=core_projection,
        extensions=tuple(sections),
    )
    observed_bytes = len(_json_bytes(projection.to_dict()))
    if observed_bytes > max_total_bytes:
        raise KernelContractError(
            "public_projection_budget_exceeded",
            "file_workspace_public@2 exceeded its global byte budget",
            details={"observed_bytes": observed_bytes},
        )
    return projection


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        json_compatible(value),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _reject_private_projection_fields(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(
                fragment in normalized for fragment in _FORBIDDEN_PUBLIC_FIELD_FRAGMENTS
            ):
                raise KernelContractError(
                    "public_extension_projection_private_field",
                    "extension projection contains a forbidden private field",
                    details={"path": f"{path}.{key}"},
                )
            _reject_private_projection_fields(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_private_projection_fields(nested, path=f"{path}[{index}]")


__all__ = [
    "CapabilityRegistryResolverPort",
    "DEFAULT_EXTENSION_SECTION_MAX_BYTES",
    "DEFAULT_EXTENSION_SECTION_MAX_ITEMS",
    "DEFAULT_PUBLIC_PROJECTION_MAX_BYTES",
    "KernelCoreProjectionProvider",
    "KernelCoreProjectionSource",
    "KernelPublicWorkspaceProjectionService",
    "assemble_file_workspace_public_v2",
    "build_public_tool_reflection",
]
