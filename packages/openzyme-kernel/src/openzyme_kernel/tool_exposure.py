from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Protocol

from openzyme_contracts import ClockPort
from openzyme_contracts import CommandToolExpansion
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordReaderPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import ToolAffordance
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolExposure
from openzyme_contracts import ToolExposureDecision
from openzyme_contracts import ToolExposureSnapshot
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts import validate_command_tool_expansion
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import freeze_json
from openzyme_contracts.identity import json_compatible

from .catalog import DeclaredToolCatalog
from .errors import KernelContractError


class CommandToolExpansionStorePort(Protocol):
    """Command-local expansion state with optimistic revision fencing."""

    def get(self, command_id: str) -> CommandToolExpansion | None: ...

    def put(
        self,
        expansion: CommandToolExpansion,
        *,
        expected_revision: int,
    ) -> None: ...


class CommandToolExpansionQueryPort(KernelRecordReaderPort, Protocol):
    """Closed indexed read boundary for one exact runtime command history."""

    def list_command_tool_expansions(
        self,
        *,
        session_id: str,
        command_id: str,
        max_items: int,
    ) -> tuple[KernelRecordSnapshot, ...]: ...


@dataclass(slots=True)
class InMemoryCommandToolExpansionStore:
    """Deterministic fake; production compositions may provide a durable port."""

    _by_command: dict[str, CommandToolExpansion] = field(default_factory=dict)

    def get(self, command_id: str) -> CommandToolExpansion | None:
        return self._by_command.get(command_id)

    def put(
        self,
        expansion: CommandToolExpansion,
        *,
        expected_revision: int,
    ) -> None:
        current = self._by_command.get(expansion.command_id)
        current_revision = 0 if current is None else current.expansion_revision
        if current is not None and current.expansion_digest == expansion.expansion_digest:
            return
        if current_revision != expected_revision:
            raise KernelContractError(
                "command_tool_expansion_revision_conflict",
                "Command-scoped tool expansion changed before settlement",
                details={
                    "command_id": expansion.command_id,
                    "expected_revision": expected_revision,
                    "actual_revision": current_revision,
                    "fallback_performed": False,
                },
            )
        self._by_command[expansion.command_id] = expansion


class ControlStoreCommandToolExpansionStore:
    """Kernel-owned durable command expansion history over the ControlStore."""

    _MAX_EXPANSIONS_PER_SESSION = 1_000

    def __init__(
        self,
        *,
        store: ControlStorePort,
        reader: CommandToolExpansionQueryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._store = store
        self._reader = reader
        self._clock = clock
        self._ids = ids

    def get(self, command_id: str) -> CommandToolExpansion | None:
        require_identifier(command_id, field_name="command_id")
        command = self._reader.read(
            entity_type="runtime_turn_command",
            entity_id=command_id,
        )
        if command is None:
            raise KernelContractError(
                "command_tool_expansion_command_missing",
                "Command expansion requires an admitted runtime turn command",
                details={"command_id": command_id, "fallback_performed": False},
            )
        session_id = command.payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise KernelContractError(
                "command_tool_expansion_command_invalid",
                "Runtime turn command lacks its exact Session identity",
                details={"command_id": command_id, "fallback_performed": False},
            )
        records = self._reader.list_command_tool_expansions(
            session_id=session_id,
            command_id=command_id,
            max_items=self._MAX_EXPANSIONS_PER_SESSION,
        )
        parsed: list[CommandToolExpansion] = []
        for record in records:
            try:
                payload = json_compatible(record.payload)
                if not isinstance(payload, dict):
                    raise TypeError("command expansion payload must be an object")
                expansion = CommandToolExpansion.from_dict(payload)
            except (TypeError, ValueError) as exc:
                raise KernelContractError(
                    "command_tool_expansion_record_invalid",
                    "Stored command expansion violates its closed contract",
                    details={
                        "expansion_id": record.entity_id,
                        "fallback_performed": False,
                    },
                ) from exc
            if expansion.expansion_id != record.entity_id:
                raise KernelContractError(
                    "command_tool_expansion_record_invalid",
                    "Stored command expansion identity differs from its record",
                    details={
                        "expansion_id": record.entity_id,
                        "fallback_performed": False,
                    },
                )
            parsed.append(expansion)
        if not parsed:
            return None
        parsed.sort(key=lambda item: item.expansion_revision)
        revisions = tuple(item.expansion_revision for item in parsed)
        expected_revisions = tuple(range(1, len(parsed) + 1))
        if revisions != expected_revisions:
            raise KernelContractError(
                "command_tool_expansion_history_drift",
                "Command expansion revisions are not unique and contiguous",
                details={
                    "command_id": command_id,
                    "observed_revisions": revisions,
                    "fallback_performed": False,
                },
            )
        return parsed[-1]

    def put(
        self,
        expansion: CommandToolExpansion,
        *,
        expected_revision: int,
    ) -> None:
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise ValueError("expected_revision must be non-negative")
        current = self.get(expansion.command_id)
        if current is not None and current.expansion_digest == expansion.expansion_digest:
            return
        current_revision = 0 if current is None else current.expansion_revision
        if current_revision != expected_revision:
            raise KernelContractError(
                "command_tool_expansion_revision_conflict",
                "Command-scoped tool expansion changed before settlement",
                details={
                    "command_id": expansion.command_id,
                    "expected_revision": expected_revision,
                    "actual_revision": current_revision,
                    "fallback_performed": False,
                },
            )
        if expansion.expansion_revision != expected_revision + 1:
            raise KernelContractError(
                "command_tool_expansion_revision_invalid",
                "New command expansion must advance exactly one revision",
                details={
                    "command_id": expansion.command_id,
                    "expected_revision": expected_revision + 1,
                    "observed_revision": expansion.expansion_revision,
                    "fallback_performed": False,
                },
            )
        if current is not None and (
            not set(current.expanded_tool_names).issubset(
                expansion.expanded_tool_names
            )
            or current.expanded_tool_names == expansion.expanded_tool_names
        ):
            raise KernelContractError(
                "command_tool_expansion_not_monotonic",
                "Command expansion may only add newly admitted Deferred tools",
                details={
                    "command_id": expansion.command_id,
                    "fallback_performed": False,
                },
            )

        command = self._reader.read(
            entity_type="runtime_turn_command",
            entity_id=expansion.command_id,
        )
        if command is None:
            raise KernelContractError(
                "command_tool_expansion_command_missing",
                "Command expansion requires an admitted runtime turn command",
            )
        session = self._reader.read(
            entity_type="session",
            entity_id=expansion.session_id,
        )
        signal_id = command.payload.get("signal_id")
        agent_member_id = command.payload.get("agent_member_id")
        if not isinstance(signal_id, str) or not isinstance(agent_member_id, str):
            raise KernelContractError(
                "command_tool_expansion_command_invalid",
                "Runtime turn command lacks its signal or member identity",
            )
        signal = self._reader.read(
            entity_type="agent_runtime_signal",
            entity_id=signal_id,
        )
        lease = self._reader.read(
            entity_type="session_runtime_lease",
            entity_id=expansion.session_id,
        )
        member = self._reader.read(
            entity_type="agent_member",
            entity_id=agent_member_id,
        )
        workflow = self._reader.read(
            entity_type="workflow_authority_binding",
            entity_id=expansion.workflow_authority_id,
        )
        exposure = self._reader.read(
            entity_type="tool_exposure_snapshot",
            entity_id=expansion.exposure_snapshot_id,
        )
        if any(
            record is None
            for record in (session, signal, lease, member, workflow, exposure)
        ):
            raise KernelContractError(
                "command_tool_expansion_identity_missing",
                "Command expansion canonical runtime identity is incomplete",
                details={
                    "command_id": expansion.command_id,
                    "fallback_performed": False,
                },
            )
        assert session is not None
        assert signal is not None
        assert lease is not None
        assert member is not None
        assert workflow is not None
        assert exposure is not None
        try:
            exposure_payload = json_compatible(exposure.payload)
            if not isinstance(exposure_payload, dict):
                raise TypeError("tool exposure payload must be an object")
            exposure_snapshot = ToolExposureSnapshot.from_dict(exposure_payload)
            validate_command_tool_expansion(exposure_snapshot, expansion)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "command_tool_expansion_exposure_drift",
                "Command expansion differs from its exact exposure snapshot",
                details={
                    "command_id": expansion.command_id,
                    "fallback_performed": False,
                },
            ) from exc
        now = _parse_instant(self._clock.now_iso(), field_name="now")
        if (
            command.payload.get("session_id") != expansion.session_id
            or command.payload.get("tool_exposure_snapshot_id")
            != expansion.exposure_snapshot_id
            or command.payload.get("tool_exposure_snapshot_digest")
            != expansion.exposure_snapshot_digest
            or command.payload.get("workflow_authority_id")
            != expansion.workflow_authority_id
            or command.payload.get("workflow_authority_epoch")
            != expansion.workflow_authority_epoch
            or command.payload.get("workflow_authority_digest")
            != expansion.workflow_authority_digest
            or signal.payload.get("status") != "claimed"
            or signal.payload.get("claim_token")
            != command.payload.get("signal_claim_token")
            or signal.payload.get("session_lease_token")
            != command.payload.get("runtime_lease_token")
            or signal.payload.get("session_fencing_token")
            != command.payload.get("runtime_fence")
            or lease.payload.get("lease_token")
            != command.payload.get("runtime_lease_token")
            or lease.payload.get("generation")
            != command.payload.get("runtime_lease_generation")
            or lease.payload.get("fencing_token")
            != command.payload.get("runtime_fence")
            or lease.payload.get("released_at") is not None
            or member.payload.get("process_epoch")
            != command.payload.get("process_epoch")
            or member.payload.get("status")
            in {"completed", "failed", "stopped", "shutdown"}
            or workflow.payload.get("status") != "active"
            or workflow.payload.get("epoch") != expansion.workflow_authority_epoch
            or workflow.payload.get("binding_digest")
            != expansion.workflow_authority_digest
            or exposure.payload.get("exposure_snapshot_digest")
            != expansion.exposure_snapshot_digest
            or _parse_instant(
                str(signal.payload.get("claim_expires_at")),
                field_name="claim_expires_at",
            )
            <= now
            or _parse_instant(
                str(lease.payload.get("expires_at")),
                field_name="lease_expires_at",
            )
            <= now
        ):
            raise KernelContractError(
                "command_tool_expansion_fence_stale",
                "Command expansion differs from current runtime fences",
                details={
                    "command_id": expansion.command_id,
                    "fallback_performed": False,
                },
            )
        capability_lease_id = signal.payload.get("capability_lease_id")
        runtime_generation = command.payload.get("runtime_lease_generation")
        runtime_fence = command.payload.get("runtime_fence")
        if (
            not isinstance(capability_lease_id, str)
            or not isinstance(runtime_generation, int)
            or isinstance(runtime_generation, bool)
            or not isinstance(runtime_fence, int)
            or isinstance(runtime_fence, bool)
        ):
            raise KernelContractError(
                "command_tool_expansion_command_invalid",
                "Runtime command lacks exact mutation authority identities",
            )
        request = UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=expansion.expansion_id,
            session_id=expansion.session_id,
            actor_id=agent_member_id,
            authority_lease_id=capability_lease_id,
            authority_generation=runtime_generation,
            authority_fence=runtime_fence,
            expected_session_version=session.state_version,
            idempotency_key=f"tool-expansion:{expansion.expansion_id}",
            command_digest=expansion.expansion_digest,
        )
        unit = self._store.begin(request)
        try:
            for record in (session, command, signal, lease, member, workflow, exposure):
                self._require_same_record(unit, record)
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="command_tool_expansion",
                    entity_id=expansion.expansion_id,
                    expected_state_version=None,
                    payload=expansion.to_dict(),
                )
            )
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=expansion.session_id,
                event_type="runtime.command.tool-expansion.created",
                source_entity_type="command_tool_expansion",
                source_entity_id=expansion.expansion_id,
                source_state_version=1,
                command_id=expansion.command_id,
                payload={
                    "command_id": expansion.command_id,
                    "expansion_revision": expansion.expansion_revision,
                    "expanded_tool_names": list(expansion.expanded_tool_names),
                    "expansion_digest": expansion.expansion_digest,
                    "authority_widened": False,
                    "route_changed": False,
                    "fallback_performed": False,
                },
            )
            unit.append_event(event)
            outbox_payload = {
                "event_id": event.event_id,
                "command_id": expansion.command_id,
                "expansion_id": expansion.expansion_id,
                "expansion_digest": expansion.expansion_digest,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=expansion.session_id,
                    topic="openzyme.kernel.runtime-command-events",
                    occurrence_id=event.event_id,
                    payload=outbox_payload,
                    payload_digest=canonical_sha256_digest(outbox_payload),
                    created_at=self._clock.now_iso(),
                )
            )
            receipt = unit.commit()
        except Exception:
            unit.rollback()
            raise
        if not receipt.committed:
            raise KernelContractError(
                "command_tool_expansion_commit_failed",
                "Command expansion was not committed",
            )

    @staticmethod
    def _require_same_record(unit, expected) -> None:  # noqa: ANN001
        current = unit.read(
            entity_type=expected.entity_type,
            entity_id=expected.entity_id,
        )
        if current is None or current.record_digest != expected.record_digest:
            raise KernelContractError(
                "command_tool_expansion_canonical_state_stale",
                "Canonical runtime identity changed before expansion commit",
            )


def _parse_instant(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise KernelContractError(
            "command_tool_expansion_time_invalid",
            f"{field_name} must be a timezone-aware ISO-8601 instant",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise KernelContractError(
            "command_tool_expansion_time_invalid",
            f"{field_name} must include a timezone",
        )
    return parsed


@dataclass(frozen=True, slots=True)
class KernelCapabilitiesInspectRuntime:
    """Mount identity for the gateway-owned ``capabilities.inspect`` runtime."""

    contract: ToolSpec

    def __post_init__(self) -> None:
        if self.contract.tool_name != "capabilities.inspect":
            raise ValueError("gateway inspection runtime requires capabilities.inspect")

    @property
    def owner_component_id(self) -> str:
        return "openzyme.kernel"

    @property
    def runtime_id(self) -> str:
        return "openzyme.kernel.runtime.capabilities.inspect"

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            status="runtime_contract_failure",
            summary="capabilities.inspect must be dispatched by the capability gateway.",
            payload={
                "effect_certainty": "no_effect",
                "mutation_applied": False,
                "fallback_performed": False,
                "retry_performed": False,
                "reconcile_required": False,
            },
            error_code="capabilities_inspect_gateway_required",
        )


@dataclass(frozen=True, slots=True)
class ToolExposureRolePolicy:
    """Distribution-owned closed presentation policy for one adopted role."""

    policy_id: str
    distribution_id: str
    release_digest: str
    subject_role: str
    decisions: tuple[ToolExposureDecision, ...]

    def __post_init__(self) -> None:
        for field_name in ("policy_id", "distribution_id", "subject_role"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.release_digest, field_name="release_digest")
        by_name = {decision.tool_name: decision for decision in self.decisions}
        if len(by_name) != len(self.decisions):
            raise ValueError("tool exposure role policy decisions must be unique")
        if not by_name:
            raise ValueError("tool exposure role policy must not be empty")
        object.__setattr__(
            self,
            "decisions",
            tuple(by_name[name] for name in sorted(by_name)),
        )

    @property
    def policy_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "tool_exposure_role_policy@1",
                "policy_id": self.policy_id,
                "distribution_id": self.distribution_id,
                "release_digest": self.release_digest,
                "subject_role": self.subject_role,
                "decisions": [decision.to_dict() for decision in self.decisions],
            }
        )


def resolve_tool_exposure_role_policy(
    *,
    policies: tuple[ToolExposureRolePolicy, ...],
    distribution_id: str,
    adopted_release_digest: str,
    subject_role: str,
    catalog: DeclaredToolCatalog,
) -> ToolExposureRolePolicy:
    """Select one exact role policy and require full catalog coverage."""

    matches = tuple(
        policy
        for policy in policies
        if policy.distribution_id == distribution_id
        and policy.release_digest == adopted_release_digest
        and policy.subject_role == subject_role
    )
    if len(matches) != 1:
        raise KernelContractError(
            "tool_exposure_role_policy_unresolved",
            "Distribution role must resolve to exactly one exposure policy",
            details={
                "distribution_id": distribution_id,
                "subject_role": subject_role,
                "matching_policy_count": len(matches),
                "fallback_performed": False,
            },
        )
    policy = matches[0]
    catalog_names = {entry.contract.tool_name for entry in catalog.entries}
    policy_names = {decision.tool_name for decision in policy.decisions}
    missing = sorted(catalog_names.difference(policy_names))
    unknown = sorted(policy_names.difference(catalog_names))
    if missing or unknown:
        raise KernelContractError(
            "tool_exposure_policy_catalog_drift",
            "Role exposure policy must decide every exact catalog tool",
            details={
                "missing_tool_names": missing,
                "unknown_tool_names": unknown,
                "fallback_performed": False,
            },
        )
    return policy


@dataclass(frozen=True, slots=True)
class ToolExposurePublicSnapshot:
    """Authority-free public inspection projection for a Distribution role."""

    snapshot_id: str
    distribution_id: str
    release_digest: str
    subject_role: str
    declared_tool_catalog_digest: str
    policy_id: str
    policy_digest: str
    available_tool_names: tuple[str, ...]
    affordances: tuple[Mapping[str, JsonValue], ...]
    tool_exposure: tuple[Mapping[str, JsonValue], ...]
    created_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "snapshot_id",
            "distribution_id",
            "subject_role",
            "policy_id",
            "created_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "release_digest",
            "declared_tool_catalog_digest",
            "policy_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        names = tuple(sorted(set(self.available_tool_names)))
        if len(names) != len(self.available_tool_names):
            raise ValueError("public available tool names must be unique")
        object.__setattr__(self, "available_tool_names", names)
        for field_name in ("affordances", "tool_exposure"):
            rows = getattr(self, field_name)
            row_names = tuple(str(row.get("tool_name")) for row in rows)
            if row_names != tuple(sorted(row_names)) or len(row_names) != len(
                set(row_names)
            ):
                raise ValueError(f"public {field_name} must be unique and sorted")
            frozen_rows: list[Mapping[str, JsonValue]] = []
            for row in rows:
                frozen = freeze_json(row, field_name=field_name)
                if not isinstance(frozen, Mapping):
                    raise ValueError(f"public {field_name} rows must be objects")
                frozen_rows.append(frozen)
            object.__setattr__(self, field_name, tuple(frozen_rows))

    @property
    def snapshot_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "schema_version": "tool_exposure_public@1",
            "snapshot_id": self.snapshot_id,
            "distribution_id": self.distribution_id,
            "release_digest": self.release_digest,
            "subject_role": self.subject_role,
            "declared_tool_catalog_digest": self.declared_tool_catalog_digest,
            "policy_id": self.policy_id,
            "policy_digest": self.policy_digest,
            "available_tool_names": list(self.available_tool_names),
            "affordances": [json_compatible(row) for row in self.affordances],
            "tool_exposure": [json_compatible(row) for row in self.tool_exposure],
            "created_at": self.created_at,
            "workflow_authority_bound": False,
        }
        if include_digest:
            payload["snapshot_digest"] = self.snapshot_digest
        return payload


def resolve_public_tool_exposure_snapshot(
    *,
    snapshot_id: str,
    catalog: DeclaredToolCatalog,
    policy: ToolExposureRolePolicy,
    available_tool_names: tuple[str, ...],
    affordances: tuple[Mapping[str, JsonValue], ...],
    created_at: str,
) -> ToolExposurePublicSnapshot:
    """Filter an authority-free public projection; Hidden names never survive."""

    policy = resolve_tool_exposure_role_policy(
        policies=(policy,),
        distribution_id=policy.distribution_id,
        adopted_release_digest=policy.release_digest,
        subject_role=policy.subject_role,
        catalog=catalog,
    )
    catalog_names = {entry.contract.tool_name for entry in catalog.entries}
    supplied_names = set(available_tool_names)
    affordance_names: list[str] = []
    for row in affordances:
        name = row.get("tool_name")
        if not isinstance(name, str):
            raise ValueError("public affordance requires an exact tool_name")
        affordance_names.append(name)
    unknown = sorted(
        supplied_names.union(affordance_names).difference(catalog_names)
    )
    if unknown or len(affordance_names) != len(set(affordance_names)):
        raise KernelContractError(
            "tool_exposure_public_input_drift",
            "Public tool projection differs from the exact declared catalog",
            details={
                "unknown_tool_names": unknown,
                "duplicate_affordance_names": sorted(
                    name
                    for name in set(affordance_names)
                    if affordance_names.count(name) > 1
                ),
                "fallback_performed": False,
            },
        )
    decisions = {decision.tool_name: decision for decision in policy.decisions}
    disclosed = {
        name
        for name, decision in decisions.items()
        if decision.exposure is not ToolExposure.HIDDEN
    }
    callable_direct = {
        name
        for name, decision in decisions.items()
        if decision.exposure is ToolExposure.DIRECT
    }
    filtered_affordances = tuple(
        dict(row)
        for row in sorted(affordances, key=lambda item: str(item["tool_name"]))
        if str(row["tool_name"]) in disclosed
    )
    public_exposure = tuple(
        {
            "tool_name": decision.tool_name,
            "exposure": decision.exposure.value,
            "reason_code": decision.reason_code,
        }
        for decision in policy.decisions
        if decision.exposure is not ToolExposure.HIDDEN
    )
    return ToolExposurePublicSnapshot(
        snapshot_id=snapshot_id,
        distribution_id=policy.distribution_id,
        release_digest=policy.release_digest,
        subject_role=policy.subject_role,
        declared_tool_catalog_digest=catalog.catalog_digest,
        policy_id=policy.policy_id,
        policy_digest=policy.policy_digest,
        available_tool_names=tuple(
            sorted(supplied_names.intersection(callable_direct))
        ),
        affordances=filtered_affordances,
        tool_exposure=public_exposure,
        created_at=created_at,
    )


def resolve_tool_exposure_snapshot(
    *,
    snapshot_id: str,
    session_id: str,
    agent_member_id: str,
    turn_id: str,
    catalog: DeclaredToolCatalog,
    affordance_snapshot: ToolAffordanceSnapshot,
    workflow_binding: WorkflowAuthorityBinding,
    policy: ToolExposureRolePolicy,
    adopted_release_digest: str,
    created_at: str,
) -> ToolExposureSnapshot:
    """Bind a complete presentation decision without changing any affordance."""

    catalog_names = tuple(entry.contract.tool_name for entry in catalog.entries)
    policy_names = tuple(decision.tool_name for decision in policy.decisions)
    missing = sorted(set(catalog_names).difference(policy_names))
    unknown = sorted(set(policy_names).difference(catalog_names))
    mismatches = {
        "policy_release": policy.release_digest != adopted_release_digest,
        "affordance_session": affordance_snapshot.session_id != session_id,
        "affordance_member": affordance_snapshot.agent_member_id != agent_member_id,
        "affordance_turn": affordance_snapshot.turn_id != turn_id,
        "affordance_catalog": (
            affordance_snapshot.declared_tool_catalog_digest != catalog.catalog_digest
        ),
        "workflow_session": workflow_binding.session_id != session_id,
        "workflow_actor": workflow_binding.authorized_actor_id != agent_member_id,
    }
    drifted = sorted(name for name, mismatch in mismatches.items() if mismatch)
    if missing or unknown or drifted:
        raise KernelContractError(
            "tool_exposure_policy_catalog_drift",
            "Tool exposure policy does not close the exact admitted catalog and turn",
            details={
                "missing_tool_names": missing,
                "unknown_tool_names": unknown,
                "drifted_fields": drifted,
                "fallback_performed": False,
            },
        )
    return ToolExposureSnapshot(
        exposure_snapshot_id=snapshot_id,
        session_id=session_id,
        agent_member_id=agent_member_id,
        turn_id=turn_id,
        subject_policy_digest=policy.policy_digest,
        declared_tool_catalog_digest=catalog.catalog_digest,
        capability_binding_digest=affordance_snapshot.capability_binding_digest,
        affordance_snapshot_id=affordance_snapshot.snapshot_id,
        affordance_snapshot_digest=affordance_snapshot.snapshot_digest,
        workflow_authority_id=workflow_binding.authority_id,
        workflow_authority_epoch=workflow_binding.epoch,
        workflow_authority_digest=workflow_binding.binding_digest,
        catalog_tool_names=catalog_names,
        decisions=policy.decisions,
        created_at=created_at,
    )


def model_visible_exposed_tool_specs(
    *,
    catalog: DeclaredToolCatalog,
    affordance_snapshot: ToolAffordanceSnapshot,
    exposure_snapshot: ToolExposureSnapshot,
    expansion: CommandToolExpansion | None = None,
) -> tuple[ToolSpec, ...]:
    _validate_snapshot_closure(
        catalog=catalog,
        affordance_snapshot=affordance_snapshot,
        exposure_snapshot=exposure_snapshot,
    )
    expanded: set[str] = set()
    if expansion is not None:
        try:
            validate_command_tool_expansion(exposure_snapshot, expansion)
        except ValueError as exc:
            raise KernelContractError(
                "command_tool_expansion_stale",
                "Command-scoped tool expansion differs from its exact exposure snapshot",
            ) from exc
        expanded.update(expansion.expanded_tool_names)
    presented = set(exposure_snapshot.names(ToolExposure.DIRECT)).union(expanded)
    callable_names = set(affordance_snapshot.model_visible_tool_names)
    return tuple(
        entry.contract
        for entry in catalog.entries
        if entry.contract.tool_name in presented
        and entry.contract.tool_name in callable_names
    )


@dataclass(frozen=True, slots=True)
class ToolExposureInspection:
    reflection: tuple[Mapping[str, JsonValue], ...]
    expansion: CommandToolExpansion | None
    undisclosed_or_unknown_count: int
    blocked_expansion_names: tuple[str, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": "tool_exposure_inspection@1",
            "tools": list(self.reflection),
            "expansion": None if self.expansion is None else self.expansion.to_dict(),
            "undisclosed_or_unknown_count": self.undisclosed_or_unknown_count,
            "blocked_expansion_names": list(self.blocked_expansion_names),
            "authority_widened": False,
            "route_changed": False,
            "approval_satisfied": False,
            "fallback_performed": False,
        }


def inspect_and_expand_tool_exposure(
    *,
    command_id: str,
    catalog: DeclaredToolCatalog,
    affordance_snapshot: ToolAffordanceSnapshot,
    exposure_snapshot: ToolExposureSnapshot,
    current_expansion: CommandToolExpansion | None,
    requested_tool_names: tuple[str, ...],
    query: str | None,
    max_items: int,
    created_at: str,
) -> ToolExposureInspection:
    """Return bounded safe reflection and one exact command-local expansion."""

    require_identifier(command_id, field_name="command_id")
    if not 1 <= max_items <= 200:
        raise ValueError("capability inspection max_items must be between 1 and 200")
    if query is not None and (not isinstance(query, str) or len(query) > 1_024):
        raise ValueError("capability inspection query must be bounded")
    _validate_snapshot_closure(
        catalog=catalog,
        affordance_snapshot=affordance_snapshot,
        exposure_snapshot=exposure_snapshot,
    )
    if current_expansion is not None:
        if current_expansion.command_id != command_id:
            raise KernelContractError(
                "command_tool_expansion_scope_drift",
                "Tool expansion belongs to another runtime command",
            )
        try:
            validate_command_tool_expansion(exposure_snapshot, current_expansion)
        except ValueError as exc:
            raise KernelContractError(
                "command_tool_expansion_stale",
                "Tool expansion differs from the exact current exposure snapshot",
            ) from exc

    decisions = {decision.tool_name: decision for decision in exposure_snapshot.decisions}
    affordances = {
        affordance.tool_name: affordance
        for affordance in affordance_snapshot.affordances
    }
    entries = {entry.contract.tool_name: entry for entry in catalog.entries}
    expanded = set(
        () if current_expansion is None else current_expansion.expanded_tool_names
    )
    undisclosed = 0
    blocked: list[str] = []
    for tool_name in sorted(set(requested_tool_names)):
        decision = decisions.get(tool_name)
        affordance = affordances.get(tool_name)
        if decision is None or decision.exposure is ToolExposure.HIDDEN:
            # Do not distinguish an unknown name from a Hidden name.
            undisclosed += 1
            continue
        if decision.exposure is ToolExposure.DIRECT:
            continue
        if affordance is None or not affordance.state.model_visible:
            blocked.append(tool_name)
            continue
        expanded.add(tool_name)

    expansion = current_expansion
    current_names = set(
        () if current_expansion is None else current_expansion.expanded_tool_names
    )
    if expanded != current_names:
        revision = 1 if current_expansion is None else current_expansion.expansion_revision + 1
        seed = canonical_sha256_digest(
            {
                "command_id": command_id,
                "exposure_snapshot_digest": exposure_snapshot.exposure_snapshot_digest,
                "expansion_revision": revision,
                "expanded_tool_names": sorted(expanded),
            }
        ).removeprefix("sha256:")[:32]
        expansion = CommandToolExpansion(
            expansion_id=f"tool-expansion-{seed}",
            command_id=command_id,
            session_id=exposure_snapshot.session_id,
            exposure_snapshot_id=exposure_snapshot.exposure_snapshot_id,
            exposure_snapshot_digest=exposure_snapshot.exposure_snapshot_digest,
            workflow_authority_id=exposure_snapshot.workflow_authority_id,
            workflow_authority_epoch=exposure_snapshot.workflow_authority_epoch,
            workflow_authority_digest=exposure_snapshot.workflow_authority_digest,
            expansion_revision=revision,
            expanded_tool_names=tuple(sorted(expanded)),
            created_at=created_at,
        )

    needle = None if query is None else query.casefold()
    reflection: list[Mapping[str, JsonValue]] = []
    for tool_name in exposure_snapshot.catalog_tool_names:
        decision = decisions[tool_name]
        if decision.exposure is ToolExposure.HIDDEN:
            continue
        entry = entries[tool_name]
        if needle and needle not in tool_name.casefold() and needle not in entry.contract.description.casefold():
            continue
        affordance = affordances.get(tool_name)
        reflection.append(
            _safe_reflection(
                entry.contract,
                decision,
                affordance,
                expanded=tool_name in expanded,
            )
        )
        if len(reflection) >= max_items:
            break
    return ToolExposureInspection(
        reflection=tuple(reflection),
        expansion=expansion,
        undisclosed_or_unknown_count=undisclosed,
        blocked_expansion_names=tuple(sorted(blocked)),
    )


def _validate_snapshot_closure(
    *,
    catalog: DeclaredToolCatalog,
    affordance_snapshot: ToolAffordanceSnapshot,
    exposure_snapshot: ToolExposureSnapshot,
) -> None:
    mismatches = {
        "catalog": (
            catalog.catalog_digest != exposure_snapshot.declared_tool_catalog_digest
            or catalog.catalog_digest
            != affordance_snapshot.declared_tool_catalog_digest
        ),
        "session": exposure_snapshot.session_id != affordance_snapshot.session_id,
        "member": (
            exposure_snapshot.agent_member_id != affordance_snapshot.agent_member_id
        ),
        "turn": exposure_snapshot.turn_id != affordance_snapshot.turn_id,
        "capability_binding": (
            exposure_snapshot.capability_binding_digest
            != affordance_snapshot.capability_binding_digest
        ),
        "affordance": (
            exposure_snapshot.affordance_snapshot_id != affordance_snapshot.snapshot_id
            or exposure_snapshot.affordance_snapshot_digest
            != affordance_snapshot.snapshot_digest
        ),
    }
    drifted = sorted(name for name, mismatch in mismatches.items() if mismatch)
    if drifted:
        raise KernelContractError(
            "tool_exposure_snapshot_stale",
            "Tool exposure differs from the exact catalog or affordance snapshot",
            details={"drifted_fields": drifted},
        )


def _safe_reflection(
    spec: ToolSpec,
    decision: ToolExposureDecision,
    affordance: ToolAffordance | None,
    *,
    expanded: bool,
) -> Mapping[str, JsonValue]:
    state = "absent" if affordance is None else affordance.state.value
    blockers = () if affordance is None else tuple(
        {
            "code": blocker.code,
            "requirement": blocker.requirement,
            "target_id": blocker.target_id,
        }
        for blocker in affordance.blockers
    )
    return {
        "tool_name": spec.tool_name,
        "description": spec.description,
        "contract_digest": spec.contract_digest,
        "exposure": decision.exposure.value,
        "exposure_reason_code": decision.reason_code,
        "affordance_state": state,
        "blockers": blockers,
        "expanded_for_command": expanded,
        "route_ids": () if affordance is None else affordance.route_ids,
    }


__all__ = [
    "CommandToolExpansionQueryPort",
    "CommandToolExpansionStorePort",
    "ControlStoreCommandToolExpansionStore",
    "InMemoryCommandToolExpansionStore",
    "KernelCapabilitiesInspectRuntime",
    "ToolExposureInspection",
    "ToolExposurePublicSnapshot",
    "ToolExposureRolePolicy",
    "inspect_and_expand_tool_exposure",
    "model_visible_exposed_tool_specs",
    "resolve_public_tool_exposure_snapshot",
    "resolve_tool_exposure_role_policy",
    "resolve_tool_exposure_snapshot",
]
