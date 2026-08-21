from dataclasses import dataclass
from dataclasses import replace

import pytest

from openzyme_contracts import FILE_WORKSPACE_CORE_SECTION_FIELDS
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import ToolAffordance
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolAffordanceState
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelQueryContext
from openzyme_extension_spi import ProjectionRequest
from openzyme_extension_spi import ProjectionResult
from openzyme_kernel import DeclaredToolCatalog
from openzyme_kernel import DeclaredToolEntry
from openzyme_kernel import KernelContractError
from openzyme_kernel import assemble_file_workspace_public_v2
from openzyme_kernel import build_public_tool_reflection


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


def _context() -> KernelQueryContext:
    return KernelQueryContext(
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="lease-1",
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("binding"),
        correlation_id="correlation-1",
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
    payload = {
        field: [] if field in array_sections else {}
        for field in FILE_WORKSPACE_CORE_SECTION_FIELDS
    }
    catalog, snapshot = _catalog_and_snapshot()
    payload["capability_binding"] = {"binding_digest": _digest("binding")}
    payload["tool_reflection"] = build_public_tool_reflection(
        declared_catalog=catalog,
        affordance_snapshot=snapshot,
    ).to_dict()
    return payload


@dataclass(frozen=True)
class _Projection:
    section_id: str
    section_contract_digest: str
    payload: dict[str, object]
    next_cursor: str | None = None

    def project(self, request: ProjectionRequest) -> ProjectionResult:
        assert request.section_id == self.section_id
        projection_digest = canonical_sha256_digest(
            {
                "section_id": self.section_id,
                "section_contract_digest": self.section_contract_digest,
                "payload": self.payload,
                "next_cursor": self.next_cursor,
            }
        )
        return ProjectionResult(
            section_id=self.section_id,
            section_contract_digest=self.section_contract_digest,
            payload=self.payload,
            next_cursor=self.next_cursor,
            projection_digest=projection_digest,
        )


def _catalog_and_snapshot() -> tuple[DeclaredToolCatalog, ToolAffordanceSnapshot]:
    spec = ToolSpec(
        tool_name="workspace.status",
        description="Inspect the current workspace.",
        input_schema={"type": "object", "additionalProperties": False},
    )
    entry = DeclaredToolEntry(
        owner_component_id="openzyme.kernel",
        runtime_id="openzyme.kernel.workspace-status@1",
        contract=spec,
    )
    catalog = DeclaredToolCatalog(entries=(entry,), catalog_digest=_digest("tools"))
    snapshot = ToolAffordanceSnapshot(
        snapshot_id="snapshot-1",
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        declared_tool_catalog_digest=catalog.catalog_digest,
        capability_binding_digest=_digest("binding"),
        authority_lease_digest=_digest("authority"),
        workspace_generation=1,
        health_observation_digest=_digest("health"),
        subject_policy_digest=_digest("policy"),
        affordances=(
            ToolAffordance(
                tool_name="workspace.status",
                tool_contract_digest=spec.contract_digest,
                state=ToolAffordanceState.AVAILABLE,
                required_authorities=(),
            ),
        ),
        created_at="2026-08-20T00:00:00Z",
        snapshot_digest="sha256:" + "0" * 64,
    )
    snapshot = replace(
        snapshot,
        snapshot_digest=canonical_sha256_digest(snapshot.digest_payload()),
    )
    return catalog, snapshot


def test_public_v2_assembles_authorized_namespaced_projection() -> None:
    section_digest = _digest("science-section")
    contributor = _Projection(
        section_id="openzyme.science@1",
        section_contract_digest=section_digest,
        payload={"attempts": [], "task_finished": False},
        next_cursor="science-page-2",
    )
    catalog, snapshot = _catalog_and_snapshot()
    core = _core_payload()
    core["tool_reflection"] = build_public_tool_reflection(
        declared_catalog=catalog,
        affordance_snapshot=snapshot,
    ).to_dict()

    projection = assemble_file_workspace_public_v2(
        release=_release(),
        core_payload=core,
        query_context=_context(),
        projection_contributors=(contributor,),
        authorized_projection_contracts={contributor.section_id: section_digest},
    )

    section = projection.to_dict()["extensions"]["openzyme.science@1"]
    assert section["payload"]["task_finished"] is False
    assert section["next_cursor"] == "science-page-2"
    assert projection.to_dict()["core"]["tool_reflection"][
        "available_tool_names"
    ] == ["workspace.status"]


def test_public_v2_rejects_mount_drift_private_fields_and_budget_overflow() -> None:
    section_digest = _digest("science-section")
    contributor = _Projection(
        section_id="openzyme.science@1",
        section_contract_digest=section_digest,
        payload={"remote_root": "/private/cluster/path"},
    )
    with pytest.raises(KernelContractError) as private:
        assemble_file_workspace_public_v2(
            release=_release(),
            core_payload=_core_payload(),
            query_context=_context(),
            projection_contributors=(contributor,),
            authorized_projection_contracts={contributor.section_id: section_digest},
        )
    assert private.value.code == "public_extension_projection_private_field"

    with pytest.raises(KernelContractError) as mount:
        assemble_file_workspace_public_v2(
            release=_release(),
            core_payload=_core_payload(),
            query_context=_context(),
            projection_contributors=(),
            authorized_projection_contracts={contributor.section_id: section_digest},
        )
    assert mount.value.code == "public_extension_projection_mount_drift"

    oversized = _Projection(
        section_id="openzyme.science@1",
        section_contract_digest=section_digest,
        payload={"items": ["x" * 128]},
    )
    with pytest.raises(KernelContractError) as budget:
        assemble_file_workspace_public_v2(
            release=_release(),
            core_payload=_core_payload(),
            query_context=_context(),
            projection_contributors=(oversized,),
            authorized_projection_contracts={oversized.section_id: section_digest},
            max_bytes_per_section=32,
        )
    assert budget.value.code == "public_extension_projection_budget_exceeded"


def test_removing_unused_plugin_changes_release_and_extension_only() -> None:
    section_digest = _digest("unused-section")
    contributor = _Projection(
        section_id="example.unused@1",
        section_contract_digest=section_digest,
        payload={"records": []},
    )
    core = _core_payload()
    with_plugin_release = _release()
    without_plugin_release = replace(
        with_plugin_release,
        extension_bundle_digest=_digest("extensions-without-unused"),
        projection_catalog_digest=_digest("projections-without-unused"),
    )
    with_plugin = assemble_file_workspace_public_v2(
        release=with_plugin_release,
        core_payload=core,
        query_context=_context(),
        projection_contributors=(contributor,),
        authorized_projection_contracts={contributor.section_id: section_digest},
    )
    without_plugin = assemble_file_workspace_public_v2(
        release=without_plugin_release,
        core_payload=core,
        query_context=replace(
            _context(),
            extension_bundle_digest=without_plugin_release.extension_bundle_digest,
        ),
        projection_contributors=(),
        authorized_projection_contracts={},
    )

    assert with_plugin.core == without_plugin.core
    assert with_plugin.release != without_plugin.release
    assert set(with_plugin.to_dict()["extensions"]) == {"example.unused@1"}
    assert without_plugin.to_dict()["extensions"] == {}


def test_public_v2_wraps_closed_core_validation_as_kernel_error() -> None:
    core = _core_payload()
    core["authority_leases"] = [
        {"agent_capability_lease_id": "legacy-lease"}
    ]
    with pytest.raises(KernelContractError) as rejected:
        assemble_file_workspace_public_v2(
            release=_release(),
            core_payload=core,
            query_context=_context(),
            projection_contributors=(),
            authorized_projection_contracts={},
        )
    assert rejected.value.code == "public_core_projection_schema_invalid"
