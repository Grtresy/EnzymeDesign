from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any
from typing import Mapping

from openzyme_contracts import AGENT_AUTHORITY_LEASE_SCHEMA_VERSION
from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import canonical_sha256_digest


LEGACY_AGENT_CAPABILITY_LEASE_SCHEMA_VERSION = "agent_capability_lease@1"
AUTHORITY_STORE_MAPPING_SCHEMA_VERSION = "agent_authority_store_mapping@1"
AUTHORITY_PHYSICAL_TABLE_NAME = "agent_capability_lease_records"

_GENERAL_CAPABILITIES = (
    "filesystem_read",
    "filesystem_write",
    "shell_process",
    "git",
    "git_lfs",
    "ordinary_network",
    "upload",
    "download",
)
_EXECUTOR_CAPABILITIES = (
    *_GENERAL_CAPABILITIES,
    "ssh",
    "rsync_scp",
    "hpc_login_workspace_crud",
    "slurm_operations",
)
_PROFILE_CAPABILITIES = {
    "general": _GENERAL_CAPABILITIES,
    "executor": _EXECUTOR_CAPABILITIES,
}
_STATE_MAP = {
    "pending_workspace": AgentAuthorityLeaseState.PENDING,
    "active": AgentAuthorityLeaseState.ACTIVE,
    "revoked": AgentAuthorityLeaseState.REVOKED,
}
LEGACY_AUTHORITY_PHYSICAL_COLUMNS = (
    "lease_id",
    "session_id",
    "agent_member_id",
    "agent_id",
    "workspace_generation",
    "profile",
    "capabilities_json",
    "capability_set_digest",
    "target_ids_json",
    "target_scope_digest",
    "policy_version",
    "policy_digest",
    "parent_lease_id",
    "idempotency_key",
    "status",
    "state_version",
    "issued_at",
    "updated_at",
    "activated_at",
    "revoked_at",
    "revocation_scope",
    "revocation_reason",
    "immutable_fingerprint",
    "canonical_digest",
    "schema_version",
)
_ROW_COLUMNS = frozenset(LEGACY_AUTHORITY_PHYSICAL_COLUMNS)


class AuthorityStoreMappingError(ValueError):
    """A physical legacy row cannot be mapped without inventing authority."""


def _legacy_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _required_string(row: Mapping[str, object], field_name: str) -> str:
    value = row[field_name]
    if not isinstance(value, str) or not value or value != value.strip():
        raise AuthorityStoreMappingError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(row: Mapping[str, object], field_name: str) -> str | None:
    value = row[field_name]
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise AuthorityStoreMappingError(f"{field_name} must be null or non-empty")
    return value


def _positive_integer(row: Mapping[str, object], field_name: str) -> int:
    value = row[field_name]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AuthorityStoreMappingError(f"{field_name} must be a positive integer")
    return value


def _string_array(row: Mapping[str, object], field_name: str) -> tuple[str, ...]:
    raw = _required_string(row, field_name)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthorityStoreMappingError(f"{field_name} must be valid JSON") from exc
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise AuthorityStoreMappingError(f"{field_name} must be a string array")
    return tuple(value)


def _verify_legacy_row(row: Mapping[str, object]) -> dict[str, Any]:
    if set(row) != _ROW_COLUMNS:
        missing = sorted(_ROW_COLUMNS - set(row))
        unexpected = sorted(set(row) - _ROW_COLUMNS)
        raise AuthorityStoreMappingError(
            f"legacy authority row shape drifted: missing={missing}, unexpected={unexpected}"
        )
    schema_version = _required_string(row, "schema_version")
    if schema_version != LEGACY_AGENT_CAPABILITY_LEASE_SCHEMA_VERSION:
        raise AuthorityStoreMappingError("unsupported legacy authority schema")

    lease_id = _required_string(row, "lease_id")
    session_id = _required_string(row, "session_id")
    agent_member_id = _required_string(row, "agent_member_id")
    agent_id = _required_string(row, "agent_id")
    workspace_generation = _positive_integer(row, "workspace_generation")
    state_version = _positive_integer(row, "state_version")
    profile = _required_string(row, "profile")
    capabilities = _string_array(row, "capabilities_json")
    expected_capabilities = _PROFILE_CAPABILITIES.get(profile)
    if expected_capabilities is None or capabilities != expected_capabilities:
        raise AuthorityStoreMappingError(
            "legacy capability tuple does not match its closed issuance template"
        )
    target_ids = _string_array(row, "target_ids_json")
    if not target_ids or target_ids != tuple(sorted(set(target_ids))):
        raise AuthorityStoreMappingError(
            "legacy target IDs must be non-empty, unique and sorted"
        )
    if _required_string(row, "capability_set_digest") != _legacy_digest(
        {"capabilities": list(capabilities)}
    ):
        raise AuthorityStoreMappingError("legacy capability set digest mismatch")
    if _required_string(row, "target_scope_digest") != _legacy_digest(
        {"target_ids": list(target_ids)}
    ):
        raise AuthorityStoreMappingError("legacy target scope digest mismatch")

    status = _required_string(row, "status")
    if status not in _STATE_MAP:
        raise AuthorityStoreMappingError("legacy authority status is unknown")
    activated_at = _optional_string(row, "activated_at")
    revoked_at = _optional_string(row, "revoked_at")
    revocation_scope = _optional_string(row, "revocation_scope")
    revocation_reason = _optional_string(row, "revocation_reason")
    if status == "pending_workspace":
        valid_state = state_version == 1 and all(
            value is None
            for value in (
                activated_at,
                revoked_at,
                revocation_scope,
                revocation_reason,
            )
        )
    elif status == "active":
        valid_state = (
            state_version == 2
            and activated_at is not None
            and all(
                value is None
                for value in (revoked_at, revocation_scope, revocation_reason)
            )
        )
    else:
        valid_state = (
            revoked_at is not None
            and revocation_scope is not None
            and revocation_reason is not None
            and state_version == (2 if activated_at is None else 3)
        )
    if not valid_state:
        raise AuthorityStoreMappingError("legacy authority lifecycle facts conflict")

    parent_lease_id = _optional_string(row, "parent_lease_id")
    policy_version = _required_string(row, "policy_version")
    policy_digest = _required_string(row, "policy_digest")
    idempotency_key = _required_string(row, "idempotency_key")
    issued_at = _required_string(row, "issued_at")
    updated_at = _required_string(row, "updated_at")
    immutable_payload = {
        "schema_version": schema_version,
        "lease_id": lease_id,
        "session_id": session_id,
        "agent_member_id": agent_member_id,
        "agent_id": agent_id,
        "workspace_generation": workspace_generation,
        "profile": profile,
        "capabilities": list(capabilities),
        "capability_set_digest": row["capability_set_digest"],
        "target_ids": list(target_ids),
        "target_scope_digest": row["target_scope_digest"],
        "policy_version": policy_version,
        "policy_digest": policy_digest,
        "parent_lease_id": parent_lease_id,
        "idempotency_key": idempotency_key,
        "issued_at": issued_at,
    }
    immutable_fingerprint = _required_string(row, "immutable_fingerprint")
    if immutable_fingerprint != _legacy_digest(immutable_payload):
        raise AuthorityStoreMappingError("legacy immutable authority identity mismatch")
    canonical_payload = {
        **immutable_payload,
        "status": status,
        "state_version": state_version,
        "updated_at": updated_at,
        "activated_at": activated_at,
        "revoked_at": revoked_at,
        "revocation_scope": revocation_scope,
        "revocation_reason": revocation_reason,
        "immutable_fingerprint": immutable_fingerprint,
    }
    canonical_digest = _required_string(row, "canonical_digest")
    if canonical_digest != _legacy_digest(canonical_payload):
        raise AuthorityStoreMappingError("legacy canonical authority digest mismatch")
    return {
        **canonical_payload,
        "canonical_digest": canonical_digest,
        "capabilities": capabilities,
        "target_ids": target_ids,
    }


def _require_targets(
    target_ids: tuple[str, ...],
    *,
    prefix: str,
    capability: str,
) -> tuple[str, ...]:
    matches = tuple(target for target in target_ids if target.startswith(prefix))
    if not matches:
        raise AuthorityStoreMappingError(
            f"legacy capability {capability!r} has no {prefix!r} target"
        )
    return matches


def _grant_operations(legacy: Mapping[str, Any]) -> dict[str, set[str]]:
    workspace_scope = (
        f"workspace:{legacy['session_id']}:{legacy['agent_member_id']}:"
        f"{legacy['workspace_generation']}"
    )
    target_ids = legacy["target_ids"]
    by_scope: dict[str, set[str]] = {}

    def add(scope_id: str, *operations: str) -> None:
        by_scope.setdefault(scope_id, set()).update(operations)

    for capability in legacy["capabilities"]:
        if capability == "filesystem_read":
            add(workspace_scope, "workspace.fs.read")
        elif capability == "filesystem_write":
            add(workspace_scope, "workspace.fs.write")
        elif capability == "shell_process":
            add(workspace_scope, "workspace.process.exec")
        elif capability == "upload":
            add(workspace_scope, "workspace.transfer.write")
        elif capability == "download":
            add(workspace_scope, "workspace.transfer.read")
        elif capability == "git":
            for target in _require_targets(
                target_ids,
                prefix="repository:",
                capability=capability,
            ):
                add(target, "workspace.git.read", "workspace.git.write")
        elif capability == "git_lfs":
            for target in _require_targets(
                target_ids,
                prefix="repository:",
                capability=capability,
            ):
                add(target, "workspace.git.lfs.read", "workspace.git.lfs.write")
        elif capability == "ordinary_network":
            for target in _require_targets(
                target_ids,
                prefix="network:",
                capability=capability,
            ):
                add(target, "workspace.network.outbound")
        elif capability == "ssh":
            for target in _require_targets(
                target_ids,
                prefix="hpc:",
                capability=capability,
            ):
                add(target, "hpc.workspace.process.exec")
        elif capability == "rsync_scp":
            for target in _require_targets(
                target_ids,
                prefix="hpc:",
                capability=capability,
            ):
                add(
                    target,
                    "hpc.workspace.transfer.read",
                    "hpc.workspace.transfer.write",
                )
        elif capability == "hpc_login_workspace_crud":
            for target in _require_targets(
                target_ids,
                prefix="hpc:",
                capability=capability,
            ):
                add(
                    target,
                    "hpc.workspace.provision",
                    "hpc.workspace.inspect",
                    "hpc.workspace.fs.read",
                    "hpc.workspace.fs.write",
                )
        elif capability == "slurm_operations":
            for target in _require_targets(
                target_ids,
                prefix="hpc:",
                capability=capability,
            ):
                add(
                    target,
                    "hpc.scheduler.submit",
                    "hpc.scheduler.observe",
                    "hpc.scheduler.cancel",
                )
        else:  # pragma: no cover - closed profile validation makes this unreachable
            raise AuthorityStoreMappingError(
                f"legacy capability {capability!r} has no authority mapping"
            )
    return by_scope


@dataclass(frozen=True, slots=True)
class AgentAuthorityStoreMappingReceipt:
    lease: AgentAuthorityLease
    physical_table_name: str
    legacy_schema_version: str
    public_schema_version: str
    legacy_canonical_digest: str
    mapping_digest: str
    schema_version: str = AUTHORITY_STORE_MAPPING_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        lease: AgentAuthorityLease,
        legacy_canonical_digest: str,
    ) -> AgentAuthorityStoreMappingReceipt:
        payload = {
            "schema_version": AUTHORITY_STORE_MAPPING_SCHEMA_VERSION,
            "physical_table_name": AUTHORITY_PHYSICAL_TABLE_NAME,
            "legacy_schema_version": LEGACY_AGENT_CAPABILITY_LEASE_SCHEMA_VERSION,
            "public_schema_version": AGENT_AUTHORITY_LEASE_SCHEMA_VERSION,
            "legacy_canonical_digest": legacy_canonical_digest,
            "lease_digest": lease.lease_digest,
        }
        return cls(
            lease=lease,
            physical_table_name=AUTHORITY_PHYSICAL_TABLE_NAME,
            legacy_schema_version=LEGACY_AGENT_CAPABILITY_LEASE_SCHEMA_VERSION,
            public_schema_version=AGENT_AUTHORITY_LEASE_SCHEMA_VERSION,
            legacy_canonical_digest=legacy_canonical_digest,
            mapping_digest=canonical_sha256_digest(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "physical_table_name": self.physical_table_name,
            "legacy_schema_version": self.legacy_schema_version,
            "public_schema_version": self.public_schema_version,
            "legacy_canonical_digest": self.legacy_canonical_digest,
            "lease": self.lease.to_dict(),
            "mapping_digest": self.mapping_digest,
        }


def map_legacy_agent_capability_lease_row(
    row: Mapping[str, object],
) -> AgentAuthorityStoreMappingReceipt:
    normalized_row = {str(key): row[key] for key in row.keys()}
    legacy = _verify_legacy_row(normalized_row)
    grants = []
    generation = legacy["workspace_generation"]
    fence = legacy["state_version"]
    for scope_id, operations in sorted(_grant_operations(legacy).items()):
        grant_seed = _legacy_digest(
            {"lease_id": legacy["lease_id"], "scope_id": scope_id}
        ).removeprefix("sha256:")[:24]
        grants.append(
            AuthorityGrant.create(
                grant_id=f"authority-grant-{grant_seed}",
                scope_id=scope_id,
                operations=tuple(sorted(operations)),
                generation=generation,
                fence=fence,
            )
        )
    lease = AgentAuthorityLease.create(
        lease_id=legacy["lease_id"],
        session_id=legacy["session_id"],
        agent_member_id=legacy["agent_member_id"],
        grants=tuple(grants),
        generation=generation,
        fence=fence,
        state=_STATE_MAP[legacy["status"]],
        issued_at=legacy["issued_at"],
        expires_at=None,
        agent_id=legacy["agent_id"],
        workspace_generation=legacy["workspace_generation"],
        parent_lease_id=legacy["parent_lease_id"],
        policy_digest=legacy["policy_digest"],
        idempotency_key=legacy["idempotency_key"],
        updated_at=legacy["updated_at"],
    )
    return AgentAuthorityStoreMappingReceipt.create(
        lease=lease,
        legacy_canonical_digest=legacy["canonical_digest"],
    )


__all__ = [
    "AUTHORITY_PHYSICAL_TABLE_NAME",
    "AUTHORITY_STORE_MAPPING_SCHEMA_VERSION",
    "LEGACY_AGENT_CAPABILITY_LEASE_SCHEMA_VERSION",
    "LEGACY_AUTHORITY_PHYSICAL_COLUMNS",
    "AgentAuthorityStoreMappingReceipt",
    "AuthorityStoreMappingError",
    "map_legacy_agent_capability_lease_row",
]
