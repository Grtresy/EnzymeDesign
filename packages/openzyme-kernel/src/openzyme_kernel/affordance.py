from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import ToolAffordance
from openzyme_contracts import ToolAffordanceBlocker
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolAffordanceState
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from .catalog import DeclaredToolCatalog
from .catalog import DeclaredToolEntry
from .composition import ActivatedPluginComposition
from .errors import KernelContractError
from .registry import CapabilityRegistry
from .registry import resolve_tool_capabilities
from .registry import version_satisfies


class ToolSubjectPolicyAction(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    HIDE = "hide"


@dataclass(frozen=True, slots=True)
class ToolSubjectPolicyDecision:
    tool_name: str
    action: ToolSubjectPolicyAction
    blocker_code: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.tool_name, field_name="tool_name")
        if self.action is ToolSubjectPolicyAction.BLOCK:
            if self.blocker_code is None:
                raise ValueError("blocked tool policy requires blocker_code")
        elif self.blocker_code is not None:
            raise ValueError("only blocked tool policy may expose blocker_code")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "tool_name": self.tool_name,
            "action": self.action.value,
            "blocker_code": self.blocker_code,
        }


def subject_policy_digest(
    *,
    session_id: str,
    agent_member_id: str,
    subject_role: str,
    task_id: str | None,
    decisions: tuple[ToolSubjectPolicyDecision, ...],
) -> str:
    return canonical_sha256_digest(
        {
            "session_id": session_id,
            "agent_member_id": agent_member_id,
            "subject_role": subject_role,
            "task_id": task_id,
            "decisions": [
                decision.to_dict()
                for decision in sorted(decisions, key=lambda item: item.tool_name)
            ],
        }
    )


@dataclass(frozen=True, slots=True)
class ToolAffordanceContext:
    session_id: str
    agent_member_id: str
    turn_id: str
    declared_catalog: DeclaredToolCatalog
    capability_binding: SessionCapabilityBindingRevision
    capability_registry: CapabilityRegistry
    authority_lease: AgentAuthorityLease
    workspace_generation: int
    workspace_ready: bool
    health_observation_digest: str
    observed_at: str
    subject_role: str
    task_id: str | None
    subject_policy_digest: str
    policy_decisions: tuple[ToolSubjectPolicyDecision, ...] = ()
    unavailable_route_ids: frozenset[str] = frozenset()
    hidden_tool_names: frozenset[str] = frozenset()
    configuration_blockers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        require_digest(
            self.health_observation_digest,
            field_name="health_observation_digest",
        )
        require_digest(
            self.subject_policy_digest,
            field_name="subject_policy_digest",
        )
        require_identifier(self.subject_role, field_name="subject_role")
        if self.task_id is not None:
            require_identifier(self.task_id, field_name="task_id")
        if self.workspace_generation < 0:
            raise ValueError("workspace_generation must be non-negative")
        if self.capability_binding.session_id != self.session_id:
            raise ValueError("capability binding belongs to another Session")
        if self.authority_lease.session_id != self.session_id:
            raise ValueError("authority lease belongs to another Session")
        if self.authority_lease.agent_member_id != self.agent_member_id:
            raise ValueError("authority lease belongs to another Agent member")
        if not self.capability_binding.has_valid_digest():
            raise ValueError("capability binding digest is invalid")
        if self.capability_registry.binding.binding_digest != (
            self.capability_binding.binding_digest
        ):
            raise ValueError("capability registry belongs to another binding")
        if not self.capability_registry.has_valid_digest():
            raise ValueError("capability registry digest is invalid")
        _parse_instant(self.observed_at, field_name="observed_at")
        decision_names = [decision.tool_name for decision in self.policy_decisions]
        if len(set(decision_names)) != len(decision_names):
            raise ValueError("tool policy decisions must be unique")
        object.__setattr__(
            self,
            "policy_decisions",
            tuple(sorted(self.policy_decisions, key=lambda item: item.tool_name)),
        )
        if self.subject_policy_digest != subject_policy_digest(
            session_id=self.session_id,
            agent_member_id=self.agent_member_id,
            subject_role=self.subject_role,
            task_id=self.task_id,
            decisions=self.policy_decisions,
        ):
            raise ValueError("subject policy digest is invalid")
        blocker_tools = [tool_name for tool_name, _ in self.configuration_blockers]
        if len(set(blocker_tools)) != len(blocker_tools):
            raise ValueError("configuration blockers must be unique by tool name")


@dataclass(frozen=True, slots=True)
class ToolDispatchAdmission:
    tool_name: str
    tool_contract_digest: str
    snapshot_digest: str
    capability_binding_digest: str
    authority_lease_digest: str
    workspace_generation: int
    route_id: str | None
    route_digest: str | None
    driver_id: str | None
    target_id: str | None
    inventory_generation: int | None
    capability_proof_digest: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_contract_digest": self.tool_contract_digest,
            "snapshot_digest": self.snapshot_digest,
            "capability_binding_digest": self.capability_binding_digest,
            "authority_lease_digest": self.authority_lease_digest,
            "workspace_generation": self.workspace_generation,
            "route_id": self.route_id,
            "route_digest": self.route_digest,
            "driver_id": self.driver_id,
            "target_id": self.target_id,
            "inventory_generation": self.inventory_generation,
            "capability_proof_digest": self.capability_proof_digest,
        }

    @property
    def admission_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


def _parse_instant(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 instant") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


def _lease_is_current(context: ToolAffordanceContext) -> bool:
    lease = context.authority_lease
    if lease.state is not AgentAuthorityLeaseState.ACTIVE:
        return False
    if lease.workspace_generation is not None and (
        lease.workspace_generation != context.workspace_generation
    ):
        return False
    if lease.expires_at is None:
        return True
    return _parse_instant(
        context.observed_at,
        field_name="observed_at",
    ) < _parse_instant(lease.expires_at, field_name="expires_at")


def _authority_allows(
    context: ToolAffordanceContext,
    operation: str,
    *,
    target_id: str | None = None,
) -> bool:
    if not _lease_is_current(context):
        return False
    accepted_scopes = {context.session_id}
    if target_id is not None:
        accepted_scopes.add(target_id)
    return any(
        operation in grant.operations and grant.scope_id in accepted_scopes
        for grant in context.authority_lease.grants
    )


def _authority_allows_any_scope(
    context: ToolAffordanceContext,
    operation: str,
) -> bool:
    return _lease_is_current(context) and context.authority_lease.allows(operation)


def _qualification_is_current(
    context: ToolAffordanceContext,
    target_id: str | None,
) -> bool:
    if target_id is None:
        return True
    binding = next(
        (
            item
            for item in context.capability_binding.inventory_bindings
            if item.target_id == target_id
        ),
        None,
    )
    if binding is None:
        return False
    return _parse_instant(
        context.observed_at,
        field_name="observed_at",
    ) < _parse_instant(
        binding.qualification_valid_until,
        field_name="qualification_valid_until",
    )


def _resolve_entry(
    entry: DeclaredToolEntry,
    context: ToolAffordanceContext,
) -> ToolAffordance:
    tool_name = entry.contract.tool_name
    required_authorities = entry.contract.required_authorities
    policy_decision = next(
        (
            decision
            for decision in context.policy_decisions
            if decision.tool_name == tool_name
        ),
        None,
    )
    if (
        policy_decision is not None
        and policy_decision.action is ToolSubjectPolicyAction.HIDE
    ):
        return ToolAffordance(
            tool_name=tool_name,
            tool_contract_digest=entry.contract.contract_digest,
            state=ToolAffordanceState.HIDDEN,
            required_authorities=required_authorities,
        )
    if tool_name in context.hidden_tool_names:
        return ToolAffordance(
            tool_name=tool_name,
            tool_contract_digest=entry.contract.contract_digest,
            state=ToolAffordanceState.HIDDEN,
            required_authorities=required_authorities,
        )
    if (
        policy_decision is not None
        and policy_decision.action is ToolSubjectPolicyAction.BLOCK
    ):
        return ToolAffordance(
            tool_name=tool_name,
            tool_contract_digest=entry.contract.contract_digest,
            state=ToolAffordanceState.BLOCKED_AUTHORITY,
            required_authorities=required_authorities,
            blockers=(
                ToolAffordanceBlocker(
                    code=policy_decision.blocker_code or "task_role_policy_denied"
                ),
            ),
        )

    configuration_blocker = dict(context.configuration_blockers).get(tool_name)
    if configuration_blocker is not None:
        return ToolAffordance(
            tool_name=tool_name,
            tool_contract_digest=entry.contract.contract_digest,
            state=ToolAffordanceState.BLOCKED_CONFIGURATION,
            required_authorities=required_authorities,
            blockers=(ToolAffordanceBlocker(code=configuration_blocker),),
        )

    if any(
        not _authority_allows_any_scope(context, authority)
        for authority in required_authorities
    ):
        return ToolAffordance(
            tool_name=tool_name,
            tool_contract_digest=entry.contract.contract_digest,
            state=ToolAffordanceState.BLOCKED_AUTHORITY,
            required_authorities=required_authorities,
            blockers=(ToolAffordanceBlocker(code="authority_requirement_unsatisfied"),),
        )

    if entry.requires_workspace and not context.workspace_ready:
        return ToolAffordance(
            tool_name=tool_name,
            tool_contract_digest=entry.contract.contract_digest,
            state=ToolAffordanceState.BLOCKED_PROVISIONING,
            required_authorities=required_authorities,
            blockers=(ToolAffordanceBlocker(code="workspace_not_ready"),),
        )

    resolution = resolve_tool_capabilities(entry, context.capability_registry)
    if resolution.blockers:
        qualification_blocked = any(
            blocker.code == "software_requirement_unsatisfied"
            for blocker in resolution.blockers
        )
        return ToolAffordance(
            tool_name=tool_name,
            tool_contract_digest=entry.contract.contract_digest,
            state=(
                ToolAffordanceState.BLOCKED_QUALIFICATION
                if qualification_blocked
                else ToolAffordanceState.BLOCKED_DEPENDENCY
            ),
            required_authorities=required_authorities,
            blockers=tuple(
                ToolAffordanceBlocker(
                    code=blocker.code,
                    requirement=blocker.requirement,
                    target_id=blocker.target_id,
                )
                for blocker in resolution.blockers
            ),
        )

    route_ids: tuple[str, ...] = ()
    if entry.requires_explicit_route:
        current_routes = tuple(
            route
            for route in resolution.routes
            if _qualification_is_current(context, route.target_id)
        )
        if not current_routes:
            expired_targets = tuple(
                sorted(
                    {
                        route.target_id
                        for route in resolution.routes
                        if route.target_id is not None
                    }
                )
            )
            return ToolAffordance(
                tool_name=tool_name,
                tool_contract_digest=entry.contract.contract_digest,
                state=ToolAffordanceState.BLOCKED_QUALIFICATION,
                required_authorities=required_authorities,
                blockers=tuple(
                    ToolAffordanceBlocker(
                        code="qualification_expired",
                        target_id=target_id,
                    )
                    for target_id in (expired_targets or (None,))
                ),
            )
        authorized_routes = tuple(
            route
            for route in current_routes
            if all(
                _authority_allows(
                    context,
                    authority,
                    target_id=route.target_id,
                )
                for authority in required_authorities
            )
        )
        if not authorized_routes:
            return ToolAffordance(
                tool_name=tool_name,
                tool_contract_digest=entry.contract.contract_digest,
                state=ToolAffordanceState.BLOCKED_AUTHORITY,
                required_authorities=required_authorities,
                blockers=(
                    ToolAffordanceBlocker(code="route_authority_unsatisfied"),
                ),
            )
        available_routes = tuple(
            route
            for route in authorized_routes
            if route.route_id not in context.unavailable_route_ids
        )
        if not available_routes:
            return ToolAffordance(
                tool_name=tool_name,
                tool_contract_digest=entry.contract.contract_digest,
                state=ToolAffordanceState.TEMPORARILY_UNAVAILABLE,
                required_authorities=required_authorities,
                route_ids=tuple(route.route_id for route in authorized_routes),
                route_refs=authorized_routes,
                blockers=(ToolAffordanceBlocker(code="all_compatible_routes_down"),),
            )
        route_ids = tuple(route.route_id for route in available_routes)
        route_refs = available_routes
    else:
        route_refs = ()

    state = (
        ToolAffordanceState.AVAILABLE_WITH_APPROVAL
        if entry.contract.approval_policy_id is not None
        else ToolAffordanceState.AVAILABLE
    )
    return ToolAffordance(
        tool_name=tool_name,
        tool_contract_digest=entry.contract.contract_digest,
        state=state,
        required_authorities=required_authorities,
        route_ids=route_ids,
        route_refs=route_refs,
    )


def resolve_tool_affordance_snapshot(
    context: ToolAffordanceContext,
    *,
    snapshot_id: str,
    created_at: str,
) -> ToolAffordanceSnapshot:
    affordances = tuple(
        _resolve_entry(entry, context) for entry in context.declared_catalog.entries
    )
    placeholder_digest = "sha256:" + "0" * 64
    snapshot = ToolAffordanceSnapshot(
        snapshot_id=snapshot_id,
        session_id=context.session_id,
        agent_member_id=context.agent_member_id,
        turn_id=context.turn_id,
        declared_tool_catalog_digest=context.declared_catalog.catalog_digest,
        capability_binding_digest=context.capability_binding.binding_digest,
        authority_lease_digest=context.authority_lease.lease_digest,
        workspace_generation=context.workspace_generation,
        health_observation_digest=context.health_observation_digest,
        subject_policy_digest=context.subject_policy_digest,
        affordances=affordances,
        created_at=created_at,
        snapshot_digest=placeholder_digest,
    )
    return replace(
        snapshot,
        snapshot_digest=canonical_sha256_digest(snapshot.digest_payload()),
    )


def inspect_tool_affordances(
    snapshot: ToolAffordanceSnapshot,
) -> tuple[dict[str, Any], ...]:
    if not snapshot.has_valid_digest():
        raise KernelContractError(
            "tool_affordance_snapshot_digest_mismatch",
            "tool affordance snapshot does not match its canonical payload",
        )
    return tuple(
        affordance.to_dict()
        for affordance in snapshot.affordances
        if affordance.state is not ToolAffordanceState.HIDDEN
    )


def model_visible_tool_specs(
    *,
    snapshot: ToolAffordanceSnapshot,
    catalog: DeclaredToolCatalog,
) -> tuple[ToolSpec, ...]:
    if not snapshot.has_valid_digest():
        raise KernelContractError(
            "tool_affordance_snapshot_digest_mismatch",
            "model tool list references an invalid affordance snapshot",
        )
    if snapshot.declared_tool_catalog_digest != catalog.catalog_digest:
        raise KernelContractError(
            "tool_affordance_stale",
            "model tool list references another declared catalog",
        )
    visible_names = set(snapshot.model_visible_tool_names)
    return tuple(
        entry.contract
        for entry in catalog.entries
        if entry.contract.tool_name in visible_names
    )


def inspect_capabilities(
    *,
    composition: ActivatedPluginComposition,
    registry: CapabilityRegistry,
    snapshot: ToolAffordanceSnapshot,
) -> dict[str, Any]:
    if composition.extension_bundle_digest != (
        registry.extension_bundle.extension_bundle_digest
    ):
        raise KernelContractError(
            "extension_bundle_registry_mismatch",
            "capability inspection references another extension bundle",
        )
    if snapshot.capability_binding_digest != registry.binding.binding_digest:
        raise KernelContractError(
            "tool_affordance_stale",
            "capability inspection references another Session binding",
        )
    return {
        "extension_bundle_digest": composition.extension_bundle_digest,
        "capability_registry_digest": registry.registry_digest,
        "plugins": [activation.safe_dict() for activation in composition.activations],
        "extension_capabilities": [
            fact.to_dict() for fact in registry.extension_bundle.capability_facts
        ],
        "resource_capabilities": [
            fact.to_dict() for fact in registry.resource_facts
        ],
        "routes": [route.to_dict() for route in registry.route_refs],
        "tools": list(inspect_tool_affordances(snapshot)),
    }


def revalidate_tool_dispatch(
    *,
    snapshot: ToolAffordanceSnapshot,
    context: ToolAffordanceContext,
    tool_name: str,
    selected_route_id: str | None,
) -> ToolDispatchAdmission:
    if not snapshot.has_valid_digest():
        raise KernelContractError(
            "tool_affordance_snapshot_digest_mismatch",
            "tool dispatch references an invalid affordance snapshot",
        )
    identity_matches = (
        snapshot.session_id == context.session_id
        and snapshot.agent_member_id == context.agent_member_id
        and snapshot.turn_id == context.turn_id
        and snapshot.declared_tool_catalog_digest
        == context.declared_catalog.catalog_digest
        and snapshot.capability_binding_digest
        == context.capability_binding.binding_digest
        and snapshot.authority_lease_digest == context.authority_lease.lease_digest
        and snapshot.workspace_generation == context.workspace_generation
        and snapshot.health_observation_digest == context.health_observation_digest
        and snapshot.subject_policy_digest == context.subject_policy_digest
    )
    if not identity_matches:
        raise KernelContractError(
            "tool_affordance_stale",
            "tool dispatch identities drifted after the bounded turn snapshot",
            details={"tool_name": tool_name},
        )
    original = next(
        (
            affordance
            for affordance in snapshot.affordances
            if affordance.tool_name == tool_name
        ),
        None,
    )
    if original is None or not original.state.model_visible:
        raise KernelContractError(
            "tool_not_afforded",
            "the selected tool was not callable in the bounded turn snapshot",
            details={"tool_name": tool_name},
        )
    current = _resolve_entry(
        context.declared_catalog.get(tool_name) or _raise_unknown_tool(tool_name),
        context,
    )
    if current.to_dict() != original.to_dict() or not current.state.model_visible:
        raise KernelContractError(
            "tool_affordance_stale",
            "tool affordance changed before dispatch",
            details={"tool_name": tool_name},
        )
    entry = context.declared_catalog.get(tool_name)
    if entry is None:
        raise KernelContractError(
            "unknown_tool",
            "tool is absent from the exact declared catalog",
            details={"tool_name": tool_name},
        )
    if entry.requires_explicit_route and selected_route_id is None:
        raise KernelContractError(
            "missing_route_id",
            "target-bound formal tools require an explicit route_id",
            details={"tool_name": tool_name},
        )
    if selected_route_id is not None and selected_route_id not in current.route_ids:
        raise KernelContractError(
            "tool_affordance_stale",
            "selected route is absent from the current exact affordance",
            details={"tool_name": tool_name, "route_id": selected_route_id},
        )
    selected_route = next(
        (
            route
            for route in current.route_refs
            if route.route_id == selected_route_id
        ),
        None,
    )
    return ToolDispatchAdmission(
        tool_name=tool_name,
        tool_contract_digest=current.tool_contract_digest,
        snapshot_digest=snapshot.snapshot_digest,
        capability_binding_digest=context.capability_binding.binding_digest,
        authority_lease_digest=context.authority_lease.lease_digest,
        workspace_generation=context.workspace_generation,
        route_id=selected_route_id,
        route_digest=None if selected_route is None else selected_route.route_digest,
        driver_id=None if selected_route is None else selected_route.driver_id,
        target_id=None if selected_route is None else selected_route.target_id,
        inventory_generation=(
            None if selected_route is None else selected_route.inventory_generation
        ),
        capability_proof_digest=(
            None if selected_route is None else selected_route.capability_proof_digest
        ),
    )


def revalidate_continuation_route(
    *,
    original_admission: ToolDispatchAdmission,
    context: ToolAffordanceContext,
) -> ToolDispatchAdmission:
    entry = context.declared_catalog.get(original_admission.tool_name)
    if entry is None:
        raise KernelContractError(
            "tool_affordance_stale",
            "continuation tool is absent from the current declared catalog",
            details={"tool_name": original_admission.tool_name},
        )
    current = _resolve_entry(entry, context)
    if not current.state.model_visible:
        raise KernelContractError(
            "tool_affordance_stale",
            "continuation route is no longer callable",
            details={
                "tool_name": original_admission.tool_name,
                "route_id": original_admission.route_id,
            },
        )
    route = next(
        (
            candidate
            for candidate in current.route_refs
            if candidate.route_id == original_admission.route_id
        ),
        None,
    )
    observed = {
        "tool_name": current.tool_name,
        "tool_contract_digest": current.tool_contract_digest,
        "capability_binding_digest": context.capability_binding.binding_digest,
        "workspace_generation": context.workspace_generation,
        "route_id": None if route is None else route.route_id,
        "route_digest": None if route is None else route.route_digest,
        "driver_id": None if route is None else route.driver_id,
        "target_id": None if route is None else route.target_id,
        "inventory_generation": (
            None if route is None else route.inventory_generation
        ),
        "capability_proof_digest": (
            None if route is None else route.capability_proof_digest
        ),
    }
    expected = {
        "tool_name": original_admission.tool_name,
        "tool_contract_digest": original_admission.tool_contract_digest,
        "capability_binding_digest": original_admission.capability_binding_digest,
        "workspace_generation": original_admission.workspace_generation,
        "route_id": original_admission.route_id,
        "route_digest": original_admission.route_digest,
        "driver_id": original_admission.driver_id,
        "target_id": original_admission.target_id,
        "inventory_generation": original_admission.inventory_generation,
        "capability_proof_digest": original_admission.capability_proof_digest,
    }
    if observed != expected:
        raise KernelContractError(
            "tool_affordance_stale",
            "continuation remains bound to its original route proof",
            details={
                "tool_name": original_admission.tool_name,
                "route_id": original_admission.route_id,
            },
        )
    return original_admission


def _raise_unknown_tool(tool_name: str) -> DeclaredToolEntry:
    raise KernelContractError(
        "unknown_tool",
        "tool is absent from the exact declared catalog",
        details={"tool_name": tool_name},
    )


__all__ = [
    "ToolAffordanceContext",
    "ToolDispatchAdmission",
    "ToolSubjectPolicyAction",
    "ToolSubjectPolicyDecision",
    "inspect_capabilities",
    "inspect_tool_affordances",
    "model_visible_tool_specs",
    "revalidate_continuation_route",
    "revalidate_tool_dispatch",
    "resolve_tool_affordance_snapshot",
    "subject_policy_digest",
    "version_satisfies",
]
