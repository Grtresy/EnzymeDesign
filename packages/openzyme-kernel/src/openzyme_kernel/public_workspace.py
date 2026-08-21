from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Protocol

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import ClockPort
from openzyme_contracts import FileWorkspaceCoreProjectionV2
from openzyme_contracts import FileWorkspaceExtensionSectionV2
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import FileWorkspaceToolReflection
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import json_compatible
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import KernelQueryContext
from openzyme_extension_spi import ProjectionContributor
from openzyme_extension_spi import ProjectionRequest

from .catalog import DeclaredToolCatalog
from .affordance import ToolAffordanceContext
from .affordance import resolve_tool_affordance_snapshot
from .affordance import subject_policy_digest
from .errors import KernelContractError
from .registry import CapabilityRegistry


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
    "runtime_outcome_consumption",
    "runtime_settlement_intent",
    "runtime_turn_command",
    "session_capability_binding_revision",
    "session_composition_pin",
    "session_repository_binding_pin",
    "session_runtime_lease",
    "task",
    "task_evidence",
    "verified_workspace_checkpoint",
    "workspace_generation",
    "workspace_publication_intent",
    "workspace_runtime_binding",
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
    clock: ClockPort
    max_items_per_entity_type: int = 200

    def __post_init__(self) -> None:
        if not 1 <= self.max_items_per_entity_type <= 1_000:
            raise ValueError("max_items_per_entity_type must be between 1 and 1000")

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
        if lease_snapshot is None or lease_snapshot.payload.get("session_id") != session_id:
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
        policy_digest = subject_policy_digest(
            session_id=session_id,
            agent_member_id=str(subject.payload["agent_member_id"]),
            subject_role=str(subject.payload["role"]),
            task_id=None,
            decisions=(),
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
                subject_role=str(subject.payload["role"]),
                task_id=None,
                subject_policy_digest=policy_digest,
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
        core_payload: dict[str, JsonValue] = {
            "session": _public_record_payload(session),
            "tasks": _payloads(records["task"]),
            "lanes": _payloads(records["lane"]),
            "agents": _payloads(records["agent_member"]),
            "protocol": {
                "records": _payloads(records["protocol_record"]),
                "inbox": _payloads(records["inbox_message"]),
            },
            "conversation": {
                "messages": _payloads(records["conversation_message"]),
                "memories": _payloads(records["memory"]),
            },
            "approvals": _payloads(records["approval_request"]),
            "authority_leases": _payloads(records["agent_authority_lease"]),
            "capability_binding": dict(binding.to_dict()),
            "runtime": {
                "signals": _payloads(records["agent_runtime_signal"]),
                "session_leases": _payloads(records["session_runtime_lease"]),
                "turn_commands": _payloads(records["runtime_turn_command"]),
                "continuation_intents": _payloads(
                    records["runtime_continuation_intent"]
                ),
                "settlement_intents": _payloads(
                    records["runtime_settlement_intent"]
                ),
                "outcome_consumptions": _payloads(
                    records["runtime_outcome_consumption"]
                ),
            },
            "workspace": {
                "generations": _payloads(records["workspace_generation"]),
                "runtime_bindings": _payloads(
                    records["workspace_runtime_binding"]
                ),
                "repository_binding_pins": _payloads(
                    records["session_repository_binding_pin"]
                ),
                "checkpoints": _payloads(
                    records["verified_workspace_checkpoint"]
                ),
                "revision_path_verifications": _payloads(
                    records["revision_path_verification"]
                ),
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
                "observations": _payloads(records["failure_observation"]),
            },
            "tool_reflection": reflection.to_dict(),
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
                item for item in snapshots if item.payload.get("parent_agent_id") is None
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
            return 0, False, canonical_sha256_digest(
                {"agent_member_id": subject_member_id, "workspace_ready": False}
            )
        candidate = candidates[0]
        generation = candidate.payload.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise KernelContractError(
                "public_projection_workspace_invalid",
                "Workspace runtime binding has an invalid generation",
            )
        ready = expected_generation == generation
        return generation, ready, candidate.record_digest


def _payloads(records: tuple[KernelRecordSnapshot, ...]) -> list[JsonValue]:
    return [_public_record_payload(item) for item in records]


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
    return payload


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
    candidates = (binding.created_at, lease.updated_at, subject_payload.get("updated_at"))
    return max(value for value in candidates if isinstance(value, str))


def build_public_tool_reflection(
    *,
    declared_catalog: DeclaredToolCatalog,
    affordance_snapshot: ToolAffordanceSnapshot,
) -> FileWorkspaceToolReflection:
    if affordance_snapshot.declared_tool_catalog_digest != declared_catalog.catalog_digest:
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
                "missing": sorted(set(authorized_projection_contracts) - set(contributors)),
                "unexpected": sorted(set(contributors) - set(authorized_projection_contracts)),
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
        _reject_private_projection_fields(result.payload, path=f"extensions.{section_id}")
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
            if any(fragment in normalized for fragment in _FORBIDDEN_PUBLIC_FIELD_FRAGMENTS):
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
