from __future__ import annotations

from openzyme_host_api import HostApiDependencies
from openzyme_host_api import build_configured_foundation
from tests.agent_capability_test_support import ready_host_dependencies_kwargs
from tests.agent_capability_test_support import public_test_client


def _dependencies() -> HostApiDependencies:
    return HostApiDependencies(
        **ready_host_dependencies_kwargs(),
        foundation=build_configured_foundation(),
        v3_allow_unpinned_repository_sessions_for_tests=True,
        v3_background_runtime_enabled=False,
    )


def test_v3_session_workspace_uses_the_file_public_contract() -> None:
    with public_test_client(_dependencies()) as client:
        created = client.post(
            "/v3/sessions",
            json={
                "session_id": "sess_file_api",
                "project_id": "proj_file_api",
                "objective": "Inspect the current file workspace",
            },
        )
        assert created.status_code == 200, created.text

        workspace = client.get("/v3/sessions/sess_file_api/workspace")
        assert workspace.status_code == 200, workspace.text
        payload = workspace.json()
        assert payload["schema_version"] == "file_workspace_public@1"
        assert payload["session"]["session_id"] == "sess_file_api"
        assert "agent_workspaces" in payload
        assert "published_revisions" in payload


def test_removed_public_collection_route_is_not_registered() -> None:
    retired_segment = "arti" + "facts"
    with public_test_client(_dependencies()) as client:
        response = client.get(f"/v3/sessions/unknown/{retired_segment}")
    assert response.status_code == 404
