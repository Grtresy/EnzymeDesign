from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_store_sqlite import AUTHORITY_PHYSICAL_TABLE_NAME
from openzyme_store_sqlite import AuthorityStoreMappingError
from openzyme_store_sqlite import map_legacy_agent_capability_lease_row


_GENERAL_CAPABILITIES = [
    "filesystem_read",
    "filesystem_write",
    "shell_process",
    "git",
    "git_lfs",
    "ordinary_network",
    "upload",
    "download",
]


def _legacy_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _legacy_row(
    *,
    profile: str = "executor",
    target_ids: list[str] | None = None,
    status: str = "active",
) -> dict[str, object]:
    capabilities = [
        *_GENERAL_CAPABILITIES,
        *(
            [
                "ssh",
                "rsync_scp",
                "hpc_login_workspace_crud",
                "slurm_operations",
            ]
            if profile == "executor"
            else []
        ),
    ]
    targets = target_ids or [
        "hpc:primary",
        "network:deployment",
        "repository:session-pinned",
    ]
    capability_set_digest = _legacy_digest({"capabilities": capabilities})
    target_scope_digest = _legacy_digest({"target_ids": targets})
    state_version = 2 if status in {"active", "revoked"} else 1
    activated_at = "2026-08-19T00:01:00+00:00" if status == "active" else None
    revoked_at = "2026-08-19T00:02:00+00:00" if status == "revoked" else None
    revocation_scope = "exact" if status == "revoked" else None
    revocation_reason = "explicit" if status == "revoked" else None
    immutable_payload = {
        "schema_version": "agent_capability_lease@1",
        "lease_id": "lease-1",
        "session_id": "session-1",
        "agent_member_id": "member-1",
        "agent_id": "agent-1",
        "workspace_generation": 7,
        "profile": profile,
        "capabilities": capabilities,
        "capability_set_digest": capability_set_digest,
        "target_ids": targets,
        "target_scope_digest": target_scope_digest,
        "policy_version": "policy-1",
        "policy_digest": "sha256:" + "a" * 64,
        "parent_lease_id": None,
        "idempotency_key": "issue-1",
        "issued_at": "2026-08-19T00:00:00+00:00",
    }
    immutable_fingerprint = _legacy_digest(immutable_payload)
    canonical_payload = {
        **immutable_payload,
        "status": status,
        "state_version": state_version,
        "updated_at": "2026-08-19T00:02:00+00:00",
        "activated_at": activated_at,
        "revoked_at": revoked_at,
        "revocation_scope": revocation_scope,
        "revocation_reason": revocation_reason,
        "immutable_fingerprint": immutable_fingerprint,
    }
    return {
        "lease_id": immutable_payload["lease_id"],
        "session_id": immutable_payload["session_id"],
        "agent_member_id": immutable_payload["agent_member_id"],
        "agent_id": immutable_payload["agent_id"],
        "workspace_generation": immutable_payload["workspace_generation"],
        "profile": profile,
        "capabilities_json": json.dumps(capabilities),
        "capability_set_digest": capability_set_digest,
        "target_ids_json": json.dumps(targets),
        "target_scope_digest": target_scope_digest,
        "policy_version": immutable_payload["policy_version"],
        "policy_digest": immutable_payload["policy_digest"],
        "parent_lease_id": None,
        "idempotency_key": immutable_payload["idempotency_key"],
        "status": status,
        "state_version": state_version,
        "issued_at": immutable_payload["issued_at"],
        "updated_at": canonical_payload["updated_at"],
        "activated_at": activated_at,
        "revoked_at": revoked_at,
        "revocation_scope": revocation_scope,
        "revocation_reason": revocation_reason,
        "immutable_fingerprint": immutable_fingerprint,
        "canonical_digest": _legacy_digest(canonical_payload),
        "schema_version": "agent_capability_lease@1",
    }


def _sqlite_row(values: dict[str, object]) -> sqlite3.Row:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    columns = ", ".join(f'"{name}"' for name in values)
    definitions = ", ".join(f'"{name}"' for name in values)
    connection.execute(f"CREATE TABLE legacy ({definitions})")
    connection.execute(
        f"INSERT INTO legacy ({columns}) VALUES ({', '.join('?' for _ in values)})",
        tuple(values.values()),
    )
    row = connection.execute("SELECT * FROM legacy").fetchone()
    assert row is not None
    return row


def test_exact_legacy_row_maps_to_operation_scoped_authority() -> None:
    receipt = map_legacy_agent_capability_lease_row(_sqlite_row(_legacy_row()))  # type: ignore[arg-type]
    lease = receipt.lease
    workspace_scope = "workspace:session-1:member-1:7"

    assert receipt.physical_table_name == AUTHORITY_PHYSICAL_TABLE_NAME
    assert receipt.legacy_schema_version == "agent_capability_lease@1"
    assert receipt.public_schema_version == "agent_authority_lease@1"
    assert lease.state is AgentAuthorityLeaseState.ACTIVE
    assert lease.generation == 7
    assert lease.workspace_generation == 7
    assert lease.fence == 2
    assert lease.expires_at is None
    assert lease.allows("workspace.process.exec", scope_id=workspace_scope)
    assert lease.allows(
        "workspace.git.write",
        scope_id="repository:session-pinned",
    )
    assert lease.allows("hpc.scheduler.submit", scope_id="hpc:primary")
    assert not lease.allows("software.hmmer", scope_id="hpc:primary")
    assert receipt.to_dict()["lease"]["lease_digest"] == lease.lease_digest


def test_mapping_rejects_tampered_legacy_digest() -> None:
    row = _legacy_row()
    row["canonical_digest"] = "sha256:" + "0" * 64

    with pytest.raises(AuthorityStoreMappingError, match="canonical"):
        map_legacy_agent_capability_lease_row(row)


def test_mapping_rejects_hpc_authority_without_hpc_target() -> None:
    row = _legacy_row(
        target_ids=["network:deployment", "repository:session-pinned"]
    )

    with pytest.raises(AuthorityStoreMappingError, match="has no 'hpc:' target"):
        map_legacy_agent_capability_lease_row(row)


def test_mapping_rejects_schema_or_row_shape_drift() -> None:
    row = _legacy_row()
    row["ambient_extension"] = "forbidden"

    with pytest.raises(AuthorityStoreMappingError, match="shape drifted"):
        map_legacy_agent_capability_lease_row(row)


def test_revoked_mapping_never_reactivates_authority() -> None:
    receipt = map_legacy_agent_capability_lease_row(_legacy_row(status="revoked"))

    assert receipt.lease.state is AgentAuthorityLeaseState.REVOKED
    assert receipt.lease.fence == 2
    assert not receipt.lease.allows("hpc.scheduler.submit", scope_id="hpc:primary")
