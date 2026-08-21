from dataclasses import replace

import pytest

from openzyme_contracts import FILE_WORKSPACE_CORE_SECTION_FIELDS
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
from openzyme_contracts import FileWorkspaceCoreProjectionV2
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import FileWorkspaceToolReflection
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import ToolAffordance
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolAffordanceState
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import load_file_workspace_public_v2_json_schema
from openzyme_contracts.public_workspace import (
    FILE_WORKSPACE_PUBLIC_TOOL_AFFORDANCE_STATES,
)
from openzyme_contracts.public_workspace import FILE_WORKSPACE_TOOL_AFFORDANCE_FIELDS
from openzyme_contracts.public_workspace import FILE_WORKSPACE_TOOL_REFLECTION_FIELDS


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _release() -> LayeredReleaseIdentity:
    return LayeredReleaseIdentity(
        kernel_contract_digest=_digest("kernel"),
        core_schema_digest=_digest("core-schema"),
        adapter_bundle_digest=_digest("adapters"),
        extension_bundle_digest=_digest("extensions"),
        declared_tool_catalog_digest=_digest("tools"),
        route_catalog_digest=_digest("routes"),
        projection_catalog_digest=_digest("projections"),
        migration_catalog_digest=_digest("migrations"),
        workspace_backend_digest=_digest("workspace"),
        host_build_digest=_digest("host"),
        client_build_digest=_digest("client"),
    )


def _core_payload() -> dict[str, object]:
    array_sections = {
        "tasks",
        "lanes",
        "agents",
        "approvals",
        "authority_leases",
        "publications",
    }
    return {
        field: [] if field in array_sections else {}
        for field in FILE_WORKSPACE_CORE_SECTION_FIELDS
    }


def _snapshot() -> ToolAffordanceSnapshot:
    snapshot = ToolAffordanceSnapshot(
        snapshot_id="snapshot-1",
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        declared_tool_catalog_digest=_digest("tools"),
        capability_binding_digest=_digest("binding"),
        authority_lease_digest=_digest("authority"),
        workspace_generation=1,
        health_observation_digest=_digest("health"),
        subject_policy_digest=_digest("policy"),
        affordances=(
            ToolAffordance(
                tool_name="workspace.status",
                tool_contract_digest=_digest("workspace.status"),
                state=ToolAffordanceState.AVAILABLE,
                required_authorities=(),
            ),
        ),
        created_at="2026-08-20T00:00:00Z",
        snapshot_digest="sha256:" + "0" * 64,
    )
    return replace(
        snapshot,
        snapshot_digest=canonical_sha256_digest(snapshot.digest_payload()),
    )


def test_affordance_snapshot_uses_zero_for_an_unprovisioned_workspace() -> None:
    snapshot = replace(_snapshot(), workspace_generation=0)
    snapshot = replace(
        snapshot,
        snapshot_digest=canonical_sha256_digest(snapshot.digest_payload()),
    )
    assert snapshot.workspace_generation == 0
    assert snapshot.has_valid_digest()

    with pytest.raises(ValueError, match="non-negative"):
        replace(_snapshot(), workspace_generation=-1)


def test_public_v2_root_and_release_identity_are_closed() -> None:
    reflection = FileWorkspaceToolReflection(
        declared_tool_catalog_digest=_digest("tools"),
        affordance_snapshot=_snapshot(),
    )
    core = _core_payload()
    core["capability_binding"] = {"binding_digest": _digest("binding")}
    core["tool_reflection"] = reflection.to_dict()
    projection = FileWorkspacePublicV2(
        release=_release(),
        core=FileWorkspaceCoreProjectionV2(core),
        extensions=(),
    )

    payload = projection.to_dict()
    assert set(payload) == {"schema_version", "release", "core", "extensions"}
    assert payload["schema_version"] == FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
    assert payload["release"]["public_contract_digest"] == (
        FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
    )
    assert FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE.endswith("version=2")
    assert payload["extensions"] == {}
    assert projection.projection_digest.startswith("sha256:")


def test_layered_release_identity_parser_is_closed_and_round_trips() -> None:
    release = _release()
    assert LayeredReleaseIdentity.from_dict(release.to_dict()) == release

    unknown = {**release.to_dict(), "legacy_tool_catalog_digest": _digest("old")}
    with pytest.raises(ValueError, match="fields are closed"):
        LayeredReleaseIdentity.from_dict(unknown)

    stale = {**release.to_dict(), "schema_version": "legacy_release@1"}
    with pytest.raises(ValueError, match="unsupported"):
        LayeredReleaseIdentity.from_dict(stale)


def test_packaged_public_v2_json_schema_matches_runtime_contract() -> None:
    schema = load_file_workspace_public_v2_json_schema()
    assert set(schema["required"]) == {
        "schema_version",
        "release",
        "core",
        "extensions",
    }
    core = schema["$defs"]["core"]
    assert set(core["required"]) == FILE_WORKSPACE_CORE_SECTION_FIELDS
    reflection = schema["$defs"]["tool_reflection"]
    assert set(reflection["required"]) == FILE_WORKSPACE_TOOL_REFLECTION_FIELDS
    affordance = schema["$defs"]["tool_affordance"]
    assert set(affordance["required"]) == FILE_WORKSPACE_TOOL_AFFORDANCE_FIELDS
    assert set(affordance["properties"]["state"]["enum"]) == (
        FILE_WORKSPACE_PUBLIC_TOOL_AFFORDANCE_STATES
    )


def test_public_v2_rejects_top_level_domain_fields_and_catalog_drift() -> None:
    core = _core_payload()
    core["scientific_attempts"] = []
    with pytest.raises(ValueError, match="core section fields are closed"):
        FileWorkspaceCoreProjectionV2(core)

    with pytest.raises(ValueError, match="another declared catalog"):
        FileWorkspaceToolReflection(
            declared_tool_catalog_digest=_digest("other-tools"),
            affordance_snapshot=_snapshot(),
        )


def test_public_v2_rejects_tool_reflection_binding_or_affordance_drift() -> None:
    reflection = FileWorkspaceToolReflection(
        declared_tool_catalog_digest=_digest("tools"),
        affordance_snapshot=_snapshot(),
    ).to_dict()
    core = _core_payload()
    core["capability_binding"] = {"binding_digest": _digest("other-binding")}
    core["tool_reflection"] = reflection
    with pytest.raises(ValueError, match="another capability binding"):
        FileWorkspaceCoreProjectionV2(core)

    core["capability_binding"] = {"binding_digest": _digest("binding")}
    core["tool_reflection"] = {
        **reflection,
        "available_tool_names": [],
    }
    with pytest.raises(ValueError, match="differ from public affordances"):
        FileWorkspaceCoreProjectionV2(core)


@pytest.mark.parametrize(
    ("section", "value", "match"),
    [
        ("tasks", {}, "section kind is invalid"),
        (
            "authority_leases",
            [{"agent_capability_lease_id": "legacy-lease"}],
            "forbidden public field",
        ),
        (
            "workspace",
            {"artifact_index": []},
            "forbidden public field",
        ),
        (
            "workspace",
            {"backend": {"host_path": "/srv/private"}},
            "forbidden public field",
        ),
        (
            "session",
            {"scientific_attempts": []},
            "forbidden public field",
        ),
        (
            "publications",
            [{"private_ref": "refs/openzyme/private/session/member/g1"}],
            "forbidden public field",
        ),
        (
            "workspace",
            {"lfs_object_locator": "/srv/lfs/aa/bb"},
            "forbidden public field",
        ),
    ],
)
def test_public_v2_rejects_wrong_core_kinds_and_removed_or_private_fields(
    section: str,
    value: object,
    match: str,
) -> None:
    core = _core_payload()
    core[section] = value
    with pytest.raises(ValueError, match=match):
        FileWorkspaceCoreProjectionV2(core)
