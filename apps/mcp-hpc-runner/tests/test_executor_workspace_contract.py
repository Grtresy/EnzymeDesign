from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_hpc_runner.config import ExecutorWorkspaceTargetConfig
from mcp_hpc_runner.config import load_config
from mcp_hpc_runner.executor_workspaces import ExecutorWorkspaceCleanupRequest
from mcp_hpc_runner.executor_workspaces import ExecutorWorkspaceProvisionRequest
from mcp_hpc_runner.executor_workspaces import ExecutorWorkspaceProvisioningService
from mcp_hpc_runner.models import ExecutorWorkspaceRunSpec
from mcp_hpc_runner.server import MCPHpcServer
from mcp_hpc_runner.workspace_revision_jobs import WorkspaceRevisionJobNoEffect
from mcp_hpc_runner.workspace_revision_jobs import WorkspaceRevisionJobService
from mcp_hpc_runner.workspace_revision_jobs import WorkspaceRevisionSourcePrepareRequest
from mcp_hpc_runner import workspace_revision_jobs


DIGEST = "sha256:" + "a" * 64
COMMIT = "1" * 40
TREE = "2" * 40


def _provision_request() -> ExecutorWorkspaceProvisionRequest:
    return ExecutorWorkspaceProvisionRequest(
        intent_id="intent_1",
        intent_digest=DIGEST,
        workspace_id="workspace_1",
        remote_workspace_generation=1,
        target_profile_digest=DIGEST,
        repository_endpoint="https://git.internal/repository.git",
        repository_remote_digest=DIGEST,
        base_commit=COMMIT,
        owner_identity_digest=DIGEST,
        idempotency_key="provision_1",
        absolute_deadline="2026-08-17T01:05:00+00:00",
    )


def _source_prepare_request(
    *,
    request_id: str = "source_request_1",
) -> WorkspaceRevisionSourcePrepareRequest:
    return WorkspaceRevisionSourcePrepareRequest(
        request_id=request_id,
        workspace_id="workspace_1",
        remote_workspace_generation=1,
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_binding_digest=DIGEST,
        repository_policy_digest=DIGEST,
        target_profile_digest=DIGEST,
        runner_policy_digest=DIGEST,
        source_commit=COMMIT,
        source_tree=TREE,
        source_ref="refs/heads/main",
        lfs_closure_manifest_digest=DIGEST,
        toolchain_digest=DIGEST,
        owner_identity_digest=DIGEST,
        absolute_deadline="2027-08-17T01:05:00+00:00",
        request_digest=DIGEST,
    )


def _source_manifest(
    request: WorkspaceRevisionSourcePrepareRequest,
    *,
    path: str = "src/main.py",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "compute_source_manifest@1",
        "manifest_id": f"manifest_{request.request_id}",
        "request_id": request.request_id,
        "workspace_id": request.workspace_id,
        "source_commit": request.source_commit,
        "source_tree": request.source_tree,
        "lfs_closure_manifest_digest": request.lfs_closure_manifest_digest,
        "binding_digest": request.repository_binding_digest,
        "repository_policy_digest": request.repository_policy_digest,
        "toolchain_digest": request.toolchain_digest,
        "owner_identity_digest": request.owner_identity_digest,
        "entries": [
            {
                "schema_version": "compute_source_manifest_entry@1",
                "path": path,
                "object_id": "3" * 40,
                "mode": "100644",
                "size_bytes": 12,
                "content_digest": DIGEST,
                "lfs_oid": None,
            }
        ],
        "created_at": "2026-08-17T01:00:00+00:00",
    }
    return {**payload, "manifest_digest": workspace_revision_jobs._digest(payload)}


def _cache_validation(
    body: dict[str, object],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    cache = body["cache"]
    assert isinstance(cache, dict)
    payload = {
        "schema_version": "verified_compute_tree_cache_validation@1",
        "cache_key": cache["cache_key"],
        "prior_entries_digest": cache["prior_entries_digest"],
        "manifest": manifest,
        "validated_at": "2026-08-17T01:01:00+00:00",
    }
    return {**payload, "validation_digest": workspace_revision_jobs._digest(payload)}


def _source_service(tmp_path: Path) -> WorkspaceRevisionJobService:
    service = WorkspaceRevisionJobService(
        SimpleNamespace(control_root=tmp_path),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )
    service._require_before_deadline = lambda _: None  # type: ignore[method-assign]
    service._qualification = lambda **_: object()  # type: ignore[method-assign]
    service._private_workspace = lambda **_: {  # type: ignore[method-assign]
        "schema_version": "executor_workspace_runner_private_locator@1",
        "workspace_id": "workspace_1",
    }
    return service


def test_activated_target_requires_native_isolation_and_proof_contract() -> None:
    with pytest.raises(ValueError, match="native positive and negative proofs"):
        ExecutorWorkspaceTargetConfig(activated=True)

    target = ExecutorWorkspaceTargetConfig(
        activated=True,
        target_profile_id="target_1",
        workspace_root="/srv/openzyme/workspaces",
        sidecar_root="/srv/openzyme-sidecars",
        os_principal_policy_id="principal-policy-v1",
        root_policy_digest=DIGEST,
        isolation_command="/usr/local/libexec/openzyme-workspace-isolation",
        credential_provider_id="credential-provider-v1",
        authenticator_id="target-authenticator-v1",
        login_alias="openzyme-target",
        toolchain_digest=DIGEST,
        native_positive_proof_digest=DIGEST,
        native_negative_proof_digest=DIGEST,
    )

    assert target.to_authority_dict()["scheduler_submit_enabled"] is False
    assert target.isolation_command == (
        "/usr/local/libexec/openzyme-workspace-isolation"
    )


def test_provision_and_cleanup_requests_are_closed_and_settlement_bound() -> None:
    provision = _provision_request()
    assert ExecutorWorkspaceProvisionRequest.from_dict(
        provision.to_dict()
    ) == provision
    with pytest.raises(ValueError, match="fields are closed"):
        ExecutorWorkspaceProvisionRequest.from_dict(
            {**provision.to_dict(), "host_path": "/tmp/repository"}
        )

    cleanup = ExecutorWorkspaceCleanupRequest(
        provision_request=provision,
        cleanup_intent_id="cleanup_1",
        cleanup_intent_digest=DIGEST,
        workspace_state_version=3,
        settlement_proof_digest=DIGEST,
        idempotency_key="cleanup_key_1",
        unsettled_effect_count=0,
    )
    assert ExecutorWorkspaceCleanupRequest.from_dict(cleanup.to_dict()) == cleanup
    with pytest.raises(ValueError, match="zero unsettled"):
        replace(cleanup, unsettled_effect_count=1)


@pytest.mark.parametrize(
    "stale_field",
    [
        "inputs",
        "expected_" + "outputs",
        "arti" + "fact_id",
        "stage_to",
        "local_path",
    ],
)
def test_workspace_runspec_rejects_every_retired_staging_field(
    stale_field: str,
) -> None:
    runspec = {
        "schema_version": "executor_workspace_runspec@1",
        "executor_hpc_workspace_id": "workspace_1",
        "executor_hpc_workspace_generation": 1,
        "repository_binding_id": "binding_1",
        "repository_binding_version": 1,
        "target_profile_digest": DIGEST,
        "cwd": ".",
        "command": ["true"],
        "execution_mode": "ssh",
        "resources": {},
        stale_field: [],
    }

    with pytest.raises(ValueError, match="forbids retired staging"):
        ExecutorWorkspaceRunSpec.from_dict(runspec)


def test_remote_scripts_delegate_isolation_and_never_directly_delete_root() -> None:
    provision_script = ExecutorWorkspaceProvisioningService._provision_script()
    cleanup_script = ExecutorWorkspaceProvisioningService._cleanup_script()

    assert '"${isolation_command}" "${isolation_operation}"' in provision_script
    assert "OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST" in provision_script
    assert '"${isolation_command}" cleanup' in cleanup_script
    assert "rm -rf" not in cleanup_script
    assert "OPENZYME_ISOLATION_CLEANUP_RECEIPT_DIGEST" in cleanup_script


def test_runner_surface_contains_only_workspace_revision_tools(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runner.toml"
    config_path.write_text(
        "\n".join(
            (
                "[runner]",
                f'transport_control_root = "{tmp_path / "control"}"',
            )
        ),
        encoding="utf-8",
    )
    server = MCPHpcServer(config_path)
    try:
        assert {tool["name"] for tool in server._tools()} == {  # noqa: SLF001
            "workspace.provision",
            "workspace.inspect",
            "workspace.verify",
            "workspace.cleanup",
            "workspace.cleanup.inspect",
            "workspace.job.prepare",
            "exec.run",
            "job.submit",
            "job.reconcile",
            "job.observe",
            "job.logs",
            "job.cancel",
        }
        for removed in (
            "store",
            "staging",
            "attempt_journal",
            "ssh_runner",
            "slurm_runner",
        ):
            assert not hasattr(server, removed)
    finally:
        server.close()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("repository_binding_version", 2),
        ("repository_binding_digest", "sha256:" + "b" * 64),
        ("source_commit", "4" * 40),
        ("source_tree", "5" * 40),
        ("lfs_closure_manifest_digest", "sha256:" + "c" * 64),
        ("toolchain_digest", "sha256:" + "d" * 64),
        ("owner_identity_digest", "sha256:" + "e" * 64),
        ("target_profile_digest", "sha256:" + "f" * 64),
    ),
)
def test_compute_tree_cache_identity_changes_for_every_frozen_dimension(
    field: str,
    value: object,
) -> None:
    request = _source_prepare_request()
    baseline = WorkspaceRevisionJobService._source_cache_identity(request)
    changed = WorkspaceRevisionJobService._source_cache_identity(
        replace(request, **{field: value})
    )

    assert workspace_revision_jobs._digest(changed) != workspace_revision_jobs._digest(
        baseline
    )


def test_compute_tree_cache_hit_always_uses_fresh_remote_validation(
    tmp_path: Path,
) -> None:
    service = _source_service(tmp_path)
    first = _source_prepare_request()
    second = replace(first, request_id="source_request_2")
    actions: list[str] = []

    def invoke(
        _qualification: object,
        action: str,
        body: dict[str, object],
        **_: object,
    ) -> dict[str, Any]:
        actions.append(action)
        request = WorkspaceRevisionSourcePrepareRequest.from_dict(
            body["request"]  # type: ignore[arg-type]
        )
        manifest = _source_manifest(request)
        return (
            _cache_validation(body, manifest)
            if action == "validate-source-cache"
            else manifest
        )

    service._invoke_wrapper = invoke  # type: ignore[method-assign]

    service.prepare_source(first)
    service.prepare_source(second)

    assert actions == ["prepare-source", "validate-source-cache"]


def test_compute_tree_cache_drift_is_no_effect_without_prepare_fallback(
    tmp_path: Path,
) -> None:
    service = _source_service(tmp_path)
    first = _source_prepare_request()
    second = replace(first, request_id="source_request_2")
    actions: list[str] = []

    def invoke(
        _qualification: object,
        action: str,
        body: dict[str, object],
        **_: object,
    ) -> dict[str, Any]:
        actions.append(action)
        request = WorkspaceRevisionSourcePrepareRequest.from_dict(
            body["request"]  # type: ignore[arg-type]
        )
        manifest = _source_manifest(
            request,
            path="src/drifted.py" if action == "validate-source-cache" else "src/main.py",
        )
        return (
            _cache_validation(body, manifest)
            if action == "validate-source-cache"
            else manifest
        )

    service._invoke_wrapper = invoke  # type: ignore[method-assign]
    service.prepare_source(first)

    with pytest.raises(WorkspaceRevisionJobNoEffect, match="fallback is forbidden"):
        service.prepare_source(second)

    assert actions == ["prepare-source", "validate-source-cache"]


@pytest.mark.parametrize(
    "removed_field",
    (
        "arti" + "fact_root",
        "arti" + "fact_fetch_timeout_seconds",
        "default_mode",
        "create_remote_dir_for_ssh",
        "apptainer_executable",
    ),
)
def test_removed_runner_execution_config_fails_closed(
    tmp_path: Path,
    removed_field: str,
) -> None:
    value = (
        '"legacy"'
        if removed_field != "arti" + "fact_fetch_timeout_seconds"
        else "120"
    )
    config_path = tmp_path / "runner.toml"
    config_path.write_text(
        f"[execution]\n{removed_field} = {value}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="execution contains unsupported fields"):
        load_config(config_path)
