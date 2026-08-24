from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import RuntimeContextSection
from openzyme_contracts import RuntimeContextSectionKind
from openzyme_contracts import RuntimeSignalAuthorityLink
from openzyme_contracts import RuntimeTurnContext
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolAffordanceState
from openzyme_contracts import ToolExposure
from openzyme_contracts import ToolExposureSnapshot
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import canonical_json_bytes
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import json_compatible

from .errors import KernelContractError


_MAX_QUERY_ITEMS = 1_000
_DEFAULT_SECTION_ITEMS = 64
_DEFAULT_SECTION_BYTES = 64 * 1024
_DEFAULT_CONTEXT_BYTES = 256 * 1024
_FORBIDDEN_FIELD_FRAGMENTS = (
    "credential",
    "secret",
    "access_token",
    "refresh_token",
    "private_key",
    "host_path",
    "remote_root",
    "login_alias",
    "scheduler_handle",
    "traceback",
    "stdout",
    "stderr",
)


@dataclass(frozen=True, slots=True)
class RuntimeContextBounds:
    """Deterministic, Distribution-independent world projection bounds."""

    max_bytes: int = _DEFAULT_CONTEXT_BYTES
    max_section_bytes: int = _DEFAULT_SECTION_BYTES
    default_max_items: int = _DEFAULT_SECTION_ITEMS
    section_max_items: tuple[tuple[RuntimeContextSectionKind, int], ...] = ()
    query_max_items: int = _MAX_QUERY_ITEMS

    def __post_init__(self) -> None:
        if not 1 <= self.max_bytes <= 1_048_576:
            raise ValueError("runtime context max_bytes must be between 1 and 1048576")
        if not 512 <= self.max_section_bytes <= self.max_bytes:
            raise ValueError("runtime context section byte bound is invalid")
        if not 1 <= self.default_max_items <= 1_000:
            raise ValueError("runtime context default item bound is invalid")
        if not 1 <= self.query_max_items <= _MAX_QUERY_ITEMS:
            raise ValueError("runtime context query bound is invalid")
        by_kind = dict(self.section_max_items)
        if len(by_kind) != len(self.section_max_items):
            raise ValueError("runtime context per-section bounds must be unique")
        for kind, maximum in self.section_max_items:
            if kind is RuntimeContextSectionKind.TRUNCATION:
                raise ValueError("truncation section has a closed derived bound")
            if not 1 <= maximum <= 1_000:
                raise ValueError("runtime context section item bound is invalid")
        object.__setattr__(
            self,
            "section_max_items",
            tuple(sorted(self.section_max_items, key=lambda item: item[0].value)),
        )

    def max_items(self, kind: RuntimeContextSectionKind) -> int:
        return dict(self.section_max_items).get(kind, self.default_max_items)


@dataclass(frozen=True, slots=True)
class RuntimeTurnContextBuildRequest:
    context_id: str
    session_id: str
    agent_id: str
    agent_member_id: str
    turn_id: str
    signal_id: str
    request_lineage_id: str
    created_at: str
    workflow_binding: WorkflowAuthorityBinding
    signal_authority_link: RuntimeSignalAuthorityLink
    capability_binding: SessionCapabilityBindingRevision
    affordance_snapshot: ToolAffordanceSnapshot
    exposure_snapshot: ToolExposureSnapshot
    task_id: str | None = None
    lane_id: str | None = None


@dataclass(slots=True)
class _SectionPlan:
    kind: RuntimeContextSectionKind
    mandatory: list[Mapping[str, JsonValue]] = field(default_factory=list)
    optional: list[Mapping[str, JsonValue]] = field(default_factory=list)
    kept_optional: list[Mapping[str, JsonValue]] = field(default_factory=list)
    source_query_bound_reached: bool = False

    @property
    def kept(self) -> tuple[Mapping[str, JsonValue], ...]:
        return tuple([*self.mandatory, *self.kept_optional])

    @property
    def omitted_count(self) -> int:
        return len(self.optional) - len(self.kept_optional)

    @property
    def first_omitted(self) -> Mapping[str, JsonValue] | None:
        if self.omitted_count == 0:
            return None
        return self.optional[len(self.kept_optional)]


@dataclass(frozen=True, slots=True)
class RuntimeTurnContextBuilder:
    reader: KernelRecordQueryPort
    bounds: RuntimeContextBounds = RuntimeContextBounds()

    def build(self, request: RuntimeTurnContextBuildRequest) -> RuntimeTurnContext:
        self._validate_request(request)
        plans = self._collect(request)
        for plan in plans.values():
            if plan.kind is not RuntimeContextSectionKind.TRUNCATION:
                self._apply_section_bounds(plan)
        context = self._context(request, plans)
        drop_order = (
            RuntimeContextSectionKind.TRANSCRIPT,
            RuntimeContextSectionKind.INBOX_PROTOCOL,
            RuntimeContextSectionKind.TASK_BOARD,
            RuntimeContextSectionKind.APPROVAL_CONTINUATION,
            RuntimeContextSectionKind.FAILURE,
            RuntimeContextSectionKind.LANE_WORKSPACE,
        )
        while context.byte_size > self.bounds.max_bytes:
            dropped = False
            for kind in drop_order:
                plan = plans[kind]
                if plan.kept_optional:
                    plan.kept_optional.pop()
                    dropped = True
                    break
            if not dropped:
                raise KernelContractError(
                    "runtime_context_current_constraints_exceed_bound",
                    "Current non-droppable runtime facts exceed the admitted context bound",
                    details={
                        "context_id": request.context_id,
                        "max_bytes": self.bounds.max_bytes,
                        "mutation_applied": False,
                        "fallback_performed": False,
                    },
                )
            context = self._context(request, plans)
        return context

    def _validate_request(self, request: RuntimeTurnContextBuildRequest) -> None:
        binding = request.workflow_binding
        link = request.signal_authority_link
        exposure = request.exposure_snapshot
        affordance = request.affordance_snapshot
        capability = request.capability_binding
        mismatches = {
            "workflow_status": binding.status is not WorkflowAuthorityStatus.ACTIVE,
            "workflow_session": binding.session_id != request.session_id,
            "workflow_actor": binding.authorized_actor_id != request.agent_member_id,
            "request_lineage": binding.request_lineage_id != request.request_lineage_id,
            "workflow_task_scope": (
                binding.task_id is not None and binding.task_id != request.task_id
            ),
            "workflow_lane_scope": (
                binding.lane_id is not None and binding.lane_id != request.lane_id
            ),
            "signal_link": (
                link.signal_id != request.signal_id
                or link.session_id != request.session_id
                or link.authority_id != binding.authority_id
                or link.authority_epoch != binding.epoch
                or link.authority_binding_digest != binding.binding_digest
            ),
            "capability_session": capability.session_id != request.session_id,
            "affordance_session": affordance.session_id != request.session_id,
            "affordance_member": affordance.agent_member_id != request.agent_member_id,
            "affordance_turn": affordance.turn_id != request.turn_id,
            "affordance_binding": (
                affordance.capability_binding_digest != capability.binding_digest
            ),
            "exposure_session": exposure.session_id != request.session_id,
            "exposure_member": exposure.agent_member_id != request.agent_member_id,
            "exposure_turn": exposure.turn_id != request.turn_id,
            "exposure_catalog": (
                exposure.declared_tool_catalog_digest
                != affordance.declared_tool_catalog_digest
            ),
            "exposure_binding": (
                exposure.capability_binding_digest != capability.binding_digest
            ),
            "exposure_affordance": (
                exposure.affordance_snapshot_id != affordance.snapshot_id
                or exposure.affordance_snapshot_digest != affordance.snapshot_digest
            ),
            "exposure_workflow": (
                exposure.workflow_authority_id != binding.authority_id
                or exposure.workflow_authority_epoch != binding.epoch
                or exposure.workflow_authority_digest != binding.binding_digest
            ),
        }
        drifted = sorted(name for name, mismatch in mismatches.items() if mismatch)
        if drifted:
            raise KernelContractError(
                "runtime_context_identity_drift",
                "Runtime context sources do not belong to one exact turn occurrence",
                details={
                    "context_id": request.context_id,
                    "drifted_fields": drifted,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )

    def _collect(
        self,
        request: RuntimeTurnContextBuildRequest,
    ) -> dict[RuntimeContextSectionKind, _SectionPlan]:
        plans = {
            kind: _SectionPlan(kind)
            for kind in RuntimeContextSectionKind
        }
        self._require_record(
            plans[RuntimeContextSectionKind.SESSION],
            entity_type="session",
            entity_id=request.session_id,
            session_id=request.session_id,
        )
        self._require_record(
            plans[RuntimeContextSectionKind.AGENT],
            entity_type="agent_member",
            entity_id=request.agent_member_id,
            session_id=request.session_id,
        )
        self._add_records(
            plans[RuntimeContextSectionKind.AGENT],
            request,
            entity_type="agent_authority_lease",
            mandatory=lambda record: (
                record.payload.get("agent_member_id") == request.agent_member_id
                and record.payload.get("state") in {"pending", "active"}
            ),
        )
        self._add_records(
            plans[RuntimeContextSectionKind.TASK_BOARD],
            request,
            entity_type="task",
            mandatory=lambda record: record.entity_id == request.task_id,
        )
        self._add_records(
            plans[RuntimeContextSectionKind.LANE_WORKSPACE],
            request,
            entity_type="lane",
            mandatory=lambda record: record.entity_id == request.lane_id,
        )
        for entity_type in (
            "workspace_generation",
            "workspace_runtime_binding",
            "session_repository_binding_pin",
            "workspace_provisioning_intent",
        ):
            self._add_records(
                plans[RuntimeContextSectionKind.LANE_WORKSPACE],
                request,
                entity_type=entity_type,
                mandatory=lambda record, member=request.agent_member_id: (
                    record.payload.get("owner_member_id") == member
                    or record.payload.get("agent_member_id") == member
                    or record.payload.get("agent_id") == request.agent_id
                ),
                tolerate_unsupported=True,
            )
        for entity_type in ("inbox_message", "protocol_record"):
            self._add_records(
                plans[RuntimeContextSectionKind.INBOX_PROTOCOL],
                request,
                entity_type=entity_type,
                mandatory=lambda record, member=request.agent_member_id: (
                    record.payload.get("recipient_actor_id") == member
                    and record.payload.get("status") in {"unread", "pending"}
                ),
            )
        for entity_type in (
            "approval_request",
            "continuation",
            "runtime_continuation_intent",
        ):
            self._add_records(
                plans[RuntimeContextSectionKind.APPROVAL_CONTINUATION],
                request,
                entity_type=entity_type,
                mandatory=lambda record: (
                    record.payload.get("status") == "pending"
                    or record.payload.get("state")
                    in {"waiting_approval", "approved", "claimed"}
                    or (
                        request.task_id is not None
                        and record.payload.get("task_id") == request.task_id
                    )
                ),
            )
        referenced_failure_ids = self._referenced_failure_ids(plans)
        self._add_records(
            plans[RuntimeContextSectionKind.FAILURE],
            request,
            entity_type="failure_observation",
            mandatory=lambda record: record.entity_id in referenced_failure_ids,
        )
        workflow_plan = plans[RuntimeContextSectionKind.WORKFLOW_AUTHORITY]
        workflow_plan.mandatory.extend(
            (
                _contract_fact(
                    "workflow_authority_binding",
                    request.workflow_binding.authority_id,
                    request.workflow_binding.binding_digest,
                    request.workflow_binding.to_dict(),
                ),
                _contract_fact(
                    "runtime_signal_authority_link",
                    request.signal_authority_link.signal_id,
                    request.signal_authority_link.link_digest,
                    request.signal_authority_link.to_dict(),
                ),
            )
        )
        capability_plan = plans[RuntimeContextSectionKind.CAPABILITY_EXPOSURE]
        affordance_payload, exposure_payload = _model_capability_exposure_payloads(
            affordance=request.affordance_snapshot,
            exposure=request.exposure_snapshot,
        )
        capability_plan.mandatory.extend(
            (
                _contract_fact(
                    "session_capability_binding_revision",
                    request.capability_binding.binding_id,
                    request.capability_binding.binding_digest,
                    request.capability_binding.to_dict(),
                ),
                _contract_fact(
                    "tool_affordance_snapshot",
                    request.affordance_snapshot.snapshot_id,
                    request.affordance_snapshot.snapshot_digest,
                    affordance_payload,
                ),
                _contract_fact(
                    "tool_exposure_snapshot",
                    request.exposure_snapshot.exposure_snapshot_id,
                    request.exposure_snapshot.exposure_snapshot_digest,
                    exposure_payload,
                ),
            )
        )
        self._add_records(
            plans[RuntimeContextSectionKind.TRANSCRIPT],
            request,
            entity_type="conversation_message",
            mandatory=lambda record: (
                record.entity_id == request.workflow_binding.source_message_id
            ),
        )
        return plans

    def _add_records(
        self,
        plan: _SectionPlan,
        request: RuntimeTurnContextBuildRequest,
        *,
        entity_type: str,
        mandatory,  # noqa: ANN001 - predicate is intentionally structural
        tolerate_unsupported: bool = False,
    ) -> None:
        try:
            records = self.reader.list_for_session(
                entity_type=entity_type,
                session_id=request.session_id,
                max_items=self.bounds.query_max_items,
            )
        except (KeyError, ValueError):
            if tolerate_unsupported:
                return
            raise
        if len(records) >= self.bounds.query_max_items:
            plan.source_query_bound_reached = True
        ordered = sorted(records, key=_record_order, reverse=True)
        for record in ordered:
            fact = _record_fact(record)
            if mandatory(record):
                plan.mandatory.append(fact)
            else:
                plan.optional.append(fact)
        plan.mandatory.sort(key=_fact_order)
        plan.optional.sort(key=_fact_order, reverse=True)

    def _require_record(
        self,
        plan: _SectionPlan,
        *,
        entity_type: str,
        entity_id: str,
        session_id: str,
    ) -> None:
        record = self.reader.read(entity_type=entity_type, entity_id=entity_id)
        if record is None or record.payload.get("session_id") != session_id:
            raise KernelContractError(
                "runtime_context_current_fact_missing",
                "A mandatory current runtime fact is absent",
                details={"entity_type": entity_type, "entity_id": entity_id},
            )
        plan.mandatory.append(_record_fact(record))

    @staticmethod
    def _referenced_failure_ids(
        plans: Mapping[RuntimeContextSectionKind, _SectionPlan],
    ) -> set[str]:
        referenced: set[str] = set()
        for plan in plans.values():
            for fact in (*plan.mandatory, *plan.optional):
                payload = fact.get("payload")
                if not isinstance(payload, Mapping):
                    continue
                for key in ("failure_id", "failure_ref"):
                    value = payload.get(key)
                    if isinstance(value, str):
                        referenced.add(value)
        return referenced

    def _apply_section_bounds(self, plan: _SectionPlan) -> None:
        max_items = self.bounds.max_items(plan.kind)
        if len(plan.mandatory) > max_items:
            raise KernelContractError(
                "runtime_context_current_constraints_exceed_bound",
                "Mandatory runtime facts exceed their section item bound",
                details={"section": plan.kind.value, "max_items": max_items},
            )
        plan.kept_optional[:] = plan.optional[: max_items - len(plan.mandatory)]
        while self._section(plan).byte_size > self.bounds.max_section_bytes:
            if not plan.kept_optional:
                raise KernelContractError(
                    "runtime_context_current_constraints_exceed_bound",
                    "Mandatory runtime facts exceed their section byte bound",
                    details={
                        "section": plan.kind.value,
                        "max_bytes": self.bounds.max_section_bytes,
                    },
                )
            plan.kept_optional.pop()

    def _context(
        self,
        request: RuntimeTurnContextBuildRequest,
        plans: Mapping[RuntimeContextSectionKind, _SectionPlan],
    ) -> RuntimeTurnContext:
        sections = [
            self._section(plans[kind])
            for kind in RuntimeContextSectionKind
            if kind is not RuntimeContextSectionKind.TRUNCATION
        ]
        truncations: list[Mapping[str, JsonValue]] = []
        for section in sections:
            plan = plans[section.kind]
            if section.omitted_count or plan.source_query_bound_reached:
                truncations.append(
                    {
                        "schema_version": "runtime_context_truncation_fact@1",
                        "section": section.kind.value,
                        "retained_count": len(section.items),
                        "known_omitted_count": section.omitted_count,
                        "source_query_bound_reached": plan.source_query_bound_reached,
                        "next_cursor": section.next_cursor,
                    }
                )
        sections.append(
            RuntimeContextSection(
                kind=RuntimeContextSectionKind.TRUNCATION,
                items=tuple(truncations),
            )
        )
        try:
            return RuntimeTurnContext(
                context_id=request.context_id,
                session_id=request.session_id,
                agent_id=request.agent_id,
                agent_member_id=request.agent_member_id,
                turn_id=request.turn_id,
                signal_id=request.signal_id,
                request_lineage_id=request.request_lineage_id,
                task_id=request.task_id,
                lane_id=request.lane_id,
                sections=tuple(sections),
                max_bytes=self.bounds.max_bytes,
                created_at=request.created_at,
            )
        except ValueError as exc:
            if "exceeds its admitted byte bound" not in str(exc):
                raise
            # The caller removes one deterministic optional fact and retries.
            return _oversized_context(
                request,
                tuple(sections),
                max_bytes=self.bounds.max_bytes,
            )

    @staticmethod
    def _section(plan: _SectionPlan) -> RuntimeContextSection:
        omitted = plan.omitted_count
        return RuntimeContextSection(
            kind=plan.kind,
            items=plan.kept,
            omitted_count=omitted,
            next_cursor=(
                None
                if omitted == 0
                else _cursor(plan.kind, plan.first_omitted or {})
            ),
        )


@dataclass(frozen=True, slots=True)
class _OversizedRuntimeContext:
    """Internal size probe used before a valid closed context can be created."""

    byte_size: int


def _oversized_context(
    request: RuntimeTurnContextBuildRequest,
    sections: tuple[RuntimeContextSection, ...],
    *,
    max_bytes: int,
) -> _OversizedRuntimeContext:
    payload = {
        "schema_version": "runtime_turn_context@1",
        "context_id": request.context_id,
        "session_id": request.session_id,
        "agent_id": request.agent_id,
        "agent_member_id": request.agent_member_id,
        "turn_id": request.turn_id,
        "signal_id": request.signal_id,
        "request_lineage_id": request.request_lineage_id,
        "task_id": request.task_id,
        "lane_id": request.lane_id,
        "sections": [section.to_dict() for section in sections],
        "max_bytes": max_bytes,
        "created_at": request.created_at,
    }
    return _OversizedRuntimeContext(byte_size=len(canonical_json_bytes(payload)))


def _model_capability_exposure_payloads(
    *,
    affordance: ToolAffordanceSnapshot,
    exposure: ToolExposureSnapshot,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project exact capability identities without disclosing Hidden names."""

    affordances = {item.tool_name: item for item in affordance.affordances}
    decisions = {item.tool_name: item for item in exposure.decisions}
    catalog_names = set(exposure.catalog_tool_names)
    if (
        set(affordances) != catalog_names
        or set(decisions) != catalog_names
        or exposure.affordance_snapshot_id != affordance.snapshot_id
        or exposure.affordance_snapshot_digest != affordance.snapshot_digest
        or exposure.declared_tool_catalog_digest
        != affordance.declared_tool_catalog_digest
        or exposure.capability_binding_digest
        != affordance.capability_binding_digest
    ):
        raise KernelContractError(
            "runtime_context_tool_exposure_identity_drift",
            "Tool exposure and affordance snapshots differ before model projection",
            details={"fallback_performed": False},
        )
    mismatched_hidden = sorted(
        name
        for name in catalog_names
        if (decisions[name].exposure is ToolExposure.HIDDEN)
        != (affordances[name].state is ToolAffordanceState.HIDDEN)
    )
    if mismatched_hidden:
        raise KernelContractError(
            "runtime_context_hidden_policy_drift",
            "Tool exposure and affordance snapshots disagree about Hidden tools",
            details={
                "mismatched_tool_count": len(mismatched_hidden),
                "fallback_performed": False,
            },
        )
    visible_names = tuple(
        sorted(
            name
            for name in catalog_names
            if decisions[name].exposure is not ToolExposure.HIDDEN
        )
    )
    hidden_count = len(catalog_names) - len(visible_names)
    affordance_payload = {
        "schema_version": "runtime_tool_affordance_context@1",
        "snapshot_id": affordance.snapshot_id,
        "snapshot_digest": affordance.snapshot_digest,
        "session_id": affordance.session_id,
        "agent_member_id": affordance.agent_member_id,
        "turn_id": affordance.turn_id,
        "declared_tool_catalog_digest": affordance.declared_tool_catalog_digest,
        "capability_binding_digest": affordance.capability_binding_digest,
        "authority_lease_digest": affordance.authority_lease_digest,
        "workspace_generation": affordance.workspace_generation,
        "health_observation_digest": affordance.health_observation_digest,
        "subject_policy_digest": affordance.subject_policy_digest,
        "visible_affordances": [
            affordances[name].to_dict() for name in visible_names
        ],
        "hidden_tool_count": hidden_count,
        "created_at": affordance.created_at,
    }
    exposure_payload = {
        "schema_version": "runtime_tool_exposure_context@1",
        "exposure_snapshot_id": exposure.exposure_snapshot_id,
        "exposure_snapshot_digest": exposure.exposure_snapshot_digest,
        "session_id": exposure.session_id,
        "agent_member_id": exposure.agent_member_id,
        "turn_id": exposure.turn_id,
        "subject_policy_digest": exposure.subject_policy_digest,
        "declared_tool_catalog_digest": exposure.declared_tool_catalog_digest,
        "capability_binding_digest": exposure.capability_binding_digest,
        "affordance_snapshot_id": exposure.affordance_snapshot_id,
        "affordance_snapshot_digest": exposure.affordance_snapshot_digest,
        "workflow_authority_id": exposure.workflow_authority_id,
        "workflow_authority_epoch": exposure.workflow_authority_epoch,
        "workflow_authority_digest": exposure.workflow_authority_digest,
        "visible_decisions": [decisions[name].to_dict() for name in visible_names],
        "hidden_tool_count": hidden_count,
        "created_at": exposure.created_at,
    }
    return affordance_payload, exposure_payload


def _record_fact(record: KernelRecordSnapshot) -> Mapping[str, JsonValue]:
    return {
        "schema_version": "runtime_context_record_fact@1",
        "entity_type": record.entity_type,
        "entity_id": record.entity_id,
        "state_version": record.state_version,
        "record_digest": record.record_digest,
        "payload": _public_value(record.payload),
    }


def _contract_fact(
    contract_kind: str,
    identity: str,
    digest: str,
    payload: Mapping[str, Any],
) -> Mapping[str, JsonValue]:
    return {
        "schema_version": "runtime_context_contract_fact@1",
        "contract_kind": contract_kind,
        "identity": identity,
        "digest": digest,
        "payload": _public_value(payload),
    }


def _public_value(value: Any) -> JsonValue:
    if isinstance(value, Mapping):
        safe: dict[str, JsonValue] = {}
        redacted: list[str] = []
        for key, item in value.items():
            name = str(key)
            lowered = name.lower()
            if any(fragment in lowered for fragment in _FORBIDDEN_FIELD_FRAGMENTS):
                redacted.append(name)
                continue
            safe[name] = _public_value(item)
        if redacted:
            safe["redacted_field_names"] = sorted(redacted)
        return safe
    if isinstance(value, tuple | list):
        return [_public_value(item) for item in value]
    return json_compatible(value)


def _record_order(record: KernelRecordSnapshot) -> tuple[str, str, int]:
    timestamp = record.payload.get("updated_at") or record.payload.get("created_at")
    return str(timestamp or ""), record.entity_id, record.state_version


def _fact_order(fact: Mapping[str, JsonValue]) -> tuple[str, str]:
    payload = fact.get("payload")
    timestamp = ""
    if isinstance(payload, Mapping):
        timestamp = str(payload.get("updated_at") or payload.get("created_at") or "")
    identity = str(fact.get("entity_id") or fact.get("identity") or "")
    return timestamp, identity


def _cursor(
    kind: RuntimeContextSectionKind,
    first_omitted: Mapping[str, JsonValue],
) -> str:
    seed = canonical_sha256_digest(
        {
            "section": kind.value,
            "first_omitted": json_compatible(first_omitted),
        }
    ).removeprefix("sha256:")[:32]
    return f"context-cursor-{kind.value}-{seed}"


__all__ = [
    "RuntimeContextBounds",
    "RuntimeTurnContextBuildRequest",
    "RuntimeTurnContextBuilder",
]
