#!/usr/bin/env python3
"""Read-only verifier for the C2 agent capability lease evidence boundary."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any


OPERATOR_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = OPERATOR_DIR.parents[3]
CHANGE_ID = "establish-agent-capability-leases"
C2_TASKS_PATH = REPOSITORY_ROOT / "openspec/changes" / CHANGE_ID / "tasks.md"
C0_OPERATOR_DIR = (
    REPOSITORY_ROOT
    / "openspec/changes/supersede-aox-hmm-artifact-cutover/operator"
)
C1_OPERATOR_DIR = (
    REPOSITORY_ROOT
    / "openspec/changes/establish-project-repository-bindings/operator"
)
MIGRATION_PATH = (
    "packages/openzyme-core/src/openzyme_core/migrations/"
    "039_v3_agent_capability_leases.sql"
)
ACCEPTANCE_REPOSITORY_PATH = (
    "openspec/changes/establish-agent-capability-leases/"
    "operator/acceptance-receipt.json"
)
BASELINE_REVISION = "57458a67d965bc01c1f878544ddebd4b15d29a62"

DOCUMENTS: dict[str, tuple[str, str]] = {
    "prerequisites": ("prerequisite-bindings.json", "binding_digest"),
    "authority_matrix": ("authority-matrix.json", "matrix_digest"),
    "policy": ("capability-policy-v1.json", "document_digest"),
    "scope_boundary": ("scope-boundary.json", "scope_digest"),
    "acceptance": ("acceptance-receipt.json", "receipt_digest"),
}

SCHEMAS = {
    "prerequisites": "agent_capability_lease_prerequisite_bindings@1",
    "authority_matrix": "agent_capability_authority_matrix@1",
    "policy": "agent_capability_policy@1",
    "scope_boundary": "agent_capability_lease_scope_boundary@1",
    "acceptance": "agent_capability_lease_acceptance@1",
}

EXPECTED_FIELDS = {
    "prerequisites": {
        "schema_id",
        "change_id",
        "source_revision",
        "c0",
        "c1",
        "status",
        "external_effects",
        "binding_digest",
    },
    "authority_matrix": {
        "schema_id",
        "change_id",
        "authorities",
        "cross_product",
        "automatic_effects",
        "budget_ownership",
        "publication_owner_present_in_c2",
        "matrix_digest",
    },
    "policy": {
        "schema_id",
        "change_id",
        "policy_version",
        "lease_policy",
        "lease_policy_digest",
        "profiles",
        "role_profile_map",
        "allowed_child_profiles",
        "target_scope_policy",
        "declaration_consumers",
        "declaration_is_runtime_proof",
        "test_readiness_is_production_proof",
        "profile_fallback_allowed",
        "implicit_profile_escalation_allowed",
        "ambient_authority_inference_allowed",
        "document_digest",
    },
    "scope_boundary": {
        "schema_id",
        "change_id",
        "c2_owns",
        "staged_cutover",
        "deferred_owners",
        "deferred_false_claims",
        "test_readiness",
        "forbidden_fallbacks",
        "legacy_execution_noninterference",
        "operator_effects",
        "eligible_successor",
        "scope_digest",
    },
    "acceptance": {
        "schema_id",
        "change_id",
        "source_revision",
        "c0_acceptance_receipt_digest",
        "c1_acceptance_receipt_digest",
        "prerequisite_bindings_digest",
        "authority_matrix_digest",
        "capability_policy_document_digest",
        "capability_policy_digest",
        "scope_boundary_digest",
        "final_evidence_digest",
        "implementation_snapshot",
        "schema",
        "focused_validation",
        "documentation",
        "openspec_validation",
        "mainline_validation",
        "scope_audit",
        "deferred_false_claims",
        "test_readiness_is_production_proof",
        "eligible_successor",
        "status",
        "issued_at",
        "receipt_digest",
    },
}

FINAL_EVIDENCE_SCHEMA = "agent_capability_lease_final_evidence@1"
FINAL_EVIDENCE_FIELDS = {
    "schema_id",
    "source_revision",
    "implementation_snapshot",
    "schema",
    "focused_validation",
    "documentation",
    "openspec_validation",
    "mainline_validation",
    "scope_audit",
    "issued_at",
    "evidence_digest",
}

GENERAL_CAPABILITIES = [
    "filesystem_read",
    "filesystem_write",
    "shell_process",
    "git",
    "git_lfs",
    "ordinary_network",
    "upload",
    "download",
]
EXECUTOR_CAPABILITIES = [
    *GENERAL_CAPABILITIES,
    "ssh",
    "rsync_scp",
    "hpc_login_workspace_crud",
    "slurm_operations",
]

DEFERRED_FALSE_CLAIMS = {
    "production_agent_git_workspace_ready_proven": False,
    "production_capsule_activation_proven": False,
    "production_capsule_network_or_transfer_proven": False,
    "production_publication_proven": False,
    "production_remote_hpc_credential_or_crud_proven": False,
    "production_approval_free_job_proven": False,
    "production_one_occurrence_sbatch_proven": False,
}

DOCUMENTATION_PATHS = (
    "docs/OpenZyme架构设计.md",
    "docs/v3/01-target-architecture.md",
    "docs/v3/02-control-plane.md",
    "docs/v3/03-capability-engines.md",
    "docs/v3/05-agent-runtime.md",
    "docs/v3/repository-service-operations.md",
    "openspec/changes/establish-agent-capability-leases/operator/README.md",
)

FOCUSED_TEST_FILES = (
    "apps/openzyme-host-api/tests/test_api.py",
    "apps/openzyme-host-api/tests/test_repository_native_clients.py",
    "apps/openzyme-host-api/tests/test_repository_runtime_pin.py",
    "apps/openzyme-host-api/tests/test_repository_transport.py",
    "apps/openzyme-host-api/tests/test_runtime_commands.py",
    "openspec/changes/establish-agent-capability-leases/operator/"
    "test_verify_agent_capability_lease.py",
    "packages/openzyme-core/tests/test_agent_capability_projection.py",
    "packages/openzyme-core/tests/test_agent_capability_repositories.py",
    "packages/openzyme-core/tests/test_agent_capability_service.py",
    "packages/openzyme-core/tests/test_agent_identity.py",
    "packages/openzyme-core/tests/test_agent_retirement_runtime_races.py",
    "packages/openzyme-core/tests/test_agent_runtime_capability_gate.py",
    "packages/openzyme-core/tests/test_agent_runtime_settlements.py",
    "packages/openzyme-core/tests/test_agent_scheduler.py",
    "packages/openzyme-core/tests/test_harness.py",
    "packages/openzyme-core/tests/test_migrations.py",
    "packages/openzyme-core/tests/test_projections.py",
    "packages/openzyme-core/tests/test_protocols.py",
    "packages/openzyme-core/tests/test_repositories.py",
    "packages/openzyme-core/tests/test_repository_credentials.py",
    "packages/openzyme-core/tests/test_scientific_attempts.py",
    "packages/openzyme-core/tests/test_world_inspection.py",
    "packages/openzyme-domain/tests/test_agent_capability_leases.py",
    "packages/openzyme-domain/tests/test_control_plane.py",
)
FOCUSED_PYTHON = ".venv/bin/python"
FOCUSED_ENVIRONMENT = {
    "DO_NOT_TRACK": "1",
    "OPENZYME_LOAD_ENV_FILES": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}
FOCUSED_RUFF_PATHS = (
    "apps",
    "packages",
    "openspec/changes/establish-agent-capability-leases/operator",
)

ALLOWED_SCOPE_PREFIXES = (
    "apps/openzyme-host-api/src/openzyme_host_api/app.py",
    "apps/openzyme-host-api/src/openzyme_host_api/v3_service.py",
    "apps/openzyme-host-api/tests/",
    "docs/OpenZyme架构设计.md",
    "docs/v3/",
    "openspec/changes/establish-agent-capability-leases/",
    "openspec/changes/execute-hpc-jobs-from-workspace-revisions/",
    "openspec/changes/provision-independent-agent-git-workspaces/",
    "openspec/changes/provision-isolated-executor-hpc-workspaces/",
    "openspec/changes/publish-and-sync-workspace-revisions/",
    "packages/openzyme-core/",
    "packages/openzyme-domain/",
    "scripts/test-resource-manifest.json",
)

# Populated from the final reviewed C2 diff before acceptance capture. The final
# verifier requires equality, not a directory-prefix subset.
EXPECTED_IMPLEMENTATION_PATHS: tuple[str, ...] = (
    "apps/openzyme-host-api/src/openzyme_host_api/app.py",
    "apps/openzyme-host-api/src/openzyme_host_api/evals.py",
    "apps/openzyme-host-api/src/openzyme_host_api/v3_service.py",
    "apps/openzyme-host-api/tests/agent_capability_test_support.py",
    "apps/openzyme-host-api/tests/architecture_qualification/composition.py",
    "apps/openzyme-host-api/tests/architecture_qualification/test_production_composition.py",
    "apps/openzyme-host-api/tests/repository_test_support.py",
    "apps/openzyme-host-api/tests/test_api.py",
    "apps/openzyme-host-api/tests/test_repository_native_clients.py",
    "apps/openzyme-host-api/tests/test_repository_transport.py",
    "apps/openzyme-host-api/tests/test_runtime_commands.py",
    "docs/OpenZyme架构设计.md",
    "docs/v3/01-target-architecture.md",
    "docs/v3/02-control-plane.md",
    "docs/v3/03-capability-engines.md",
    "docs/v3/05-agent-runtime.md",
    "docs/v3/repository-service-operations.md",
    "openspec/changes/establish-agent-capability-leases/design.md",
    "openspec/changes/establish-agent-capability-leases/operator/README.md",
    "openspec/changes/establish-agent-capability-leases/operator/authority-matrix.json",
    "openspec/changes/establish-agent-capability-leases/operator/capability-policy-v1.json",
    "openspec/changes/establish-agent-capability-leases/operator/capture_final_evidence.py",
    "openspec/changes/establish-agent-capability-leases/operator/generate_acceptance_receipt.py",
    "openspec/changes/establish-agent-capability-leases/operator/prerequisite-bindings.json",
    "openspec/changes/establish-agent-capability-leases/operator/scope-boundary.json",
    "openspec/changes/establish-agent-capability-leases/operator/test_verify_agent_capability_lease.py",
    "openspec/changes/establish-agent-capability-leases/operator/verify_agent_capability_lease.py",
    "openspec/changes/establish-agent-capability-leases/proposal.md",
    "openspec/changes/establish-agent-capability-leases/specs/agent-capability-lease/spec.md",
    "openspec/changes/establish-agent-capability-leases/tasks.md",
    "openspec/changes/execute-hpc-jobs-from-workspace-revisions/design.md",
    "openspec/changes/execute-hpc-jobs-from-workspace-revisions/proposal.md",
    "openspec/changes/execute-hpc-jobs-from-workspace-revisions/specs/controlled-operation-execution/spec.md",
    "openspec/changes/execute-hpc-jobs-from-workspace-revisions/specs/mcp-hpc-runner/spec.md",
    "openspec/changes/execute-hpc-jobs-from-workspace-revisions/specs/workspace-revision-execution/spec.md",
    "openspec/changes/execute-hpc-jobs-from-workspace-revisions/tasks.md",
    "openspec/changes/provision-independent-agent-git-workspaces/design.md",
    "openspec/changes/provision-independent-agent-git-workspaces/proposal.md",
    "openspec/changes/provision-independent-agent-git-workspaces/specs/agent-git-workspace/spec.md",
    "openspec/changes/provision-independent-agent-git-workspaces/tasks.md",
    "openspec/changes/provision-isolated-executor-hpc-workspaces/design.md",
    "openspec/changes/provision-isolated-executor-hpc-workspaces/proposal.md",
    "openspec/changes/provision-isolated-executor-hpc-workspaces/specs/executor-hpc-workspace/spec.md",
    "openspec/changes/provision-isolated-executor-hpc-workspaces/specs/mcp-hpc-runner/spec.md",
    "openspec/changes/provision-isolated-executor-hpc-workspaces/tasks.md",
    "openspec/changes/publish-and-sync-workspace-revisions/design.md",
    "openspec/changes/publish-and-sync-workspace-revisions/proposal.md",
    "openspec/changes/publish-and-sync-workspace-revisions/specs/workspace-publication/spec.md",
    "openspec/changes/publish-and-sync-workspace-revisions/tasks.md",
    "packages/openzyme-core/src/openzyme_core/__init__.py",
    "packages/openzyme-core/src/openzyme_core/agent_capability_projection.py",
    "packages/openzyme-core/src/openzyme_core/agent_capability_repositories.py",
    "packages/openzyme-core/src/openzyme_core/agent_capability_service.py",
    "packages/openzyme-core/src/openzyme_core/agent_identity.py",
    "packages/openzyme-core/src/openzyme_core/agent_runtime.py",
    "packages/openzyme-core/src/openzyme_core/agent_scheduler.py",
    "packages/openzyme-core/src/openzyme_core/continuation_delivery.py",
    "packages/openzyme-core/src/openzyme_core/harness.py",
    "packages/openzyme-core/src/openzyme_core/migration_assets.py",
    "packages/openzyme-core/src/openzyme_core/migrations/039_v3_agent_capability_leases.sql",
    "packages/openzyme-core/src/openzyme_core/mutation_authority.py",
    "packages/openzyme-core/src/openzyme_core/projections.py",
    "packages/openzyme-core/src/openzyme_core/protocol_tools.py",
    "packages/openzyme-core/src/openzyme_core/protocols.py",
    "packages/openzyme-core/src/openzyme_core/repositories.py",
    "packages/openzyme-core/src/openzyme_core/repository_credentials.py",
    "packages/openzyme-core/src/openzyme_core/runtime_signal_occurrences.py",
    "packages/openzyme-core/src/openzyme_core/subagents.py",
    "packages/openzyme-core/src/openzyme_core/teammates.py",
    "packages/openzyme-core/src/openzyme_core/world_inspection.py",
    "packages/openzyme-core/tests/test_agent_capability_projection.py",
    "packages/openzyme-core/tests/test_agent_capability_repositories.py",
    "packages/openzyme-core/tests/test_agent_capability_service.py",
    "packages/openzyme-core/tests/test_agent_retirement_runtime_races.py",
    "packages/openzyme-core/tests/test_agent_runtime_capability_gate.py",
    "packages/openzyme-core/tests/test_agent_scheduler.py",
    "packages/openzyme-core/tests/test_harness.py",
    "packages/openzyme-core/tests/test_migrations.py",
    "packages/openzyme-core/tests/test_projections.py",
    "packages/openzyme-core/tests/test_protocols.py",
    "packages/openzyme-core/tests/test_reliability_repositories.py",
    "packages/openzyme-core/tests/test_repositories.py",
    "packages/openzyme-core/tests/test_repository_credentials.py",
    "packages/openzyme-core/tests/test_runtime_consistency.py",
    "packages/openzyme-core/tests/test_sandbox_workspace.py",
    "packages/openzyme-core/tests/test_scientific_attempts.py",
    "packages/openzyme-core/tests/test_world_inspection.py",
    "packages/openzyme-domain/src/openzyme_domain/__init__.py",
    "packages/openzyme-domain/src/openzyme_domain/agent_capability_leases.py",
    "packages/openzyme-domain/src/openzyme_domain/control_plane.py",
    "packages/openzyme-domain/tests/test_agent_capability_leases.py",
    "packages/openzyme-domain/tests/test_control_plane.py",
    "scripts/test-resource-manifest.json",
)

PRODUCTION_SOURCE_PREFIXES = (
    "apps/openzyme-host-api/src/",
    "packages/openzyme-core/src/",
    "packages/openzyme-domain/src/",
)
DEFERRED_IMPLEMENTATION_NAME_FRAGMENTS = (
    "agentgitworkspace",
    "capsuleactivation",
    "capsulerunner",
    "executorhpcworkspace",
    "oneoccurrencesbatch",
    "publishedrevision",
    "slurmsubmission",
    "workspacepublication",
    "workspacerevisionjob",
)
DEFERRED_IMPORT_ROOTS = {
    "asyncssh",
    "fabric",
    "httpx",
    "paramiko",
    "requests",
    "scp",
}
DEFERRED_EFFECT_CALLS = {
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
    "os.popen",
    "os.system",
    "shutil.copy",
    "shutil.copy2",
    "shutil.copyfile",
    "shutil.copytree",
    "shutil.move",
    "socket.create_connection",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.run",
    "urllib.request.urlopen",
}
DEFERRED_EFFECT_METHODS = {
    "clone",
    "download",
    "fetch",
    "pull",
    "push",
    "rsync",
    "sbatch",
    "scp",
    "ssh",
    "submit",
    "upload",
    "worktree",
}
DEFERRED_ROUTE_FRAGMENTS = (
    "/capsule",
    "/hpc",
    "/jobs",
    "/publication",
    "/publish",
)

MAINLINE_CONFIGURATION_PATHS = (
    "apps/openzyme-web-ui/package.json",
    "pyproject.toml",
    "pytest.ini",
    "scripts/check-mainline.sh",
    "scripts/check-v3-architecture-qualification.sh",
    "scripts/test-affected-scope-map.json",
    "scripts/test-gate.toml",
    "scripts/test-resource-manifest.json",
)
MAINLINE_LOCK_PATHS = (
    "apps/openzyme-web-ui/npm-shrinkwrap.json",
    "apps/openzyme-web-ui/package-lock.json",
    "apps/openzyme-web-ui/pnpm-lock.yaml",
    "apps/openzyme-web-ui/yarn.lock",
    "skills-lock.json",
    "uv.lock",
)

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def digest_value(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


def digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def is_allowed_scope_path(path: str) -> bool:
    return any(
        path.startswith(prefix) if prefix.endswith("/") else path == prefix
        for prefix in ALLOWED_SCOPE_PREFIXES
    )


def _qualified_name(node: ast.expr, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        owner = _qualified_name(node.value, aliases)
        if owner is None:
            return None
        return f"{owner}.{node.attr}"
    return None


def audit_added_production_ast(
    *,
    path: str,
    content: bytes,
    added_lines: set[int],
) -> None:
    module = ast.parse(content.decode("utf-8"), filename=path)
    aliases: dict[str, str] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"

    for node in ast.walk(module):
        line = getattr(node, "lineno", None)
        if line not in added_lines:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [item.name for item in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            roots = {module_name.split(".")[0] for module_name in modules}
            forbidden = sorted(roots & DEFERRED_IMPORT_ROOTS)
            if forbidden:
                raise ValueError(
                    f"C2 deferred implementation import at {path}:{line}: "
                    + ", ".join(forbidden)
                )
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            normalized = re.sub(r"[^a-z0-9]", "", node.name.lower())
            if any(
                fragment in normalized
                for fragment in DEFERRED_IMPLEMENTATION_NAME_FRAGMENTS
            ):
                raise ValueError(
                    f"C2 deferred owner symbol at {path}:{line}: {node.name}"
                )
        if not isinstance(node, ast.Call):
            continue
        qualified = _qualified_name(node.func, aliases)
        method = qualified.rsplit(".", 1)[-1] if qualified is not None else None
        if qualified in DEFERRED_EFFECT_CALLS or method in DEFERRED_EFFECT_METHODS:
            raise ValueError(
                f"C2 deferred effect call at {path}:{line}: {qualified}"
            )
        if method in {"get", "post", "put", "patch", "delete", "add_api_route"}:
            route = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
            if isinstance(route, str) and any(
                fragment in route.lower() for fragment in DEFERRED_ROUTE_FRAGMENTS
            ):
                raise ValueError(
                    f"C2 deferred product route at {path}:{line}: {route}"
                )


def _path_exists_at_revision(path: str, revision: str) -> bool:
    return (
        subprocess.run(
            ("git", "cat-file", "-e", f"{revision}:{path}"),
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def _added_line_numbers(path: str, revision: str | None) -> set[int]:
    content = snapshot_file_bytes(path, revision)
    if not _path_exists_at_revision(path, BASELINE_REVISION):
        return set(range(1, content.count(b"\n") + 2))
    arguments = [
        "git",
        "diff",
        "--no-ext-diff",
        "--unified=0",
        BASELINE_REVISION,
    ]
    if revision is not None:
        arguments.append(revision)
    arguments.extend(("--", path))
    diff = subprocess.run(
        tuple(arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    added: set[int] = set()
    for match in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.MULTILINE):
        start = int(match.group(1))
        count = 1 if match.group(2) is None else int(match.group(2))
        added.update(range(start, start + count))
    return added


def verify_deferred_implementation_boundary(
    paths: list[str],
    *,
    revision: str | None,
) -> dict[str, Any]:
    production_paths = sorted(
        path
        for path in paths
        if path.endswith(".py")
        and any(path.startswith(prefix) for prefix in PRODUCTION_SOURCE_PREFIXES)
    )
    for path in production_paths:
        audit_added_production_ast(
            path=path,
            content=snapshot_file_bytes(path, revision),
            added_lines=_added_line_numbers(path, revision),
        )
    policy = deferred_ast_policy()
    return {
        "ast_policy_digest": digest_value(policy),
        "audited_production_paths": production_paths,
        "audited_production_path_digest": digest_value(production_paths),
        "forbidden_findings": [],
    }


def deferred_ast_policy() -> dict[str, Any]:
    return {
        "name_fragments": list(DEFERRED_IMPLEMENTATION_NAME_FRAGMENTS),
        "import_roots": sorted(DEFERRED_IMPORT_ROOTS),
        "effect_calls": sorted(DEFERRED_EFFECT_CALLS),
        "effect_methods": sorted(DEFERRED_EFFECT_METHODS),
        "route_fragments": list(DEFERRED_ROUTE_FRAGMENTS),
    }


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"operator evidence must be a JSON object: {path}")
    return value


def load_document(name: str, *, required: bool = True) -> dict[str, Any] | None:
    filename, _ = DOCUMENTS[name]
    path = OPERATOR_DIR / filename
    if not path.exists():
        if required:
            raise ValueError(f"required operator document is missing: {filename}")
        return None
    return load_json_object(path)


def verify_document(name: str, value: dict[str, Any]) -> str:
    actual_fields = set(value)
    expected_fields = EXPECTED_FIELDS[name]
    if actual_fields != expected_fields:
        raise ValueError(
            f"{name} fields are not closed: "
            f"missing={sorted(expected_fields - actual_fields)}, "
            f"extra={sorted(actual_fields - expected_fields)}"
        )
    if value["schema_id"] != SCHEMAS[name]:
        raise ValueError(f"{name} schema identity is invalid")
    _, digest_field = DOCUMENTS[name]
    preimage = {key: item for key, item in value.items() if key != digest_field}
    actual_digest = digest_value(preimage)
    if value[digest_field] != actual_digest:
        raise ValueError(f"{name} canonical digest does not match")
    return actual_digest


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load prerequisite verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_output(*arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_bytes(*arguments: str) -> bytes:
    return subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _git_file(revision: str, path: str) -> bytes:
    return _git_bytes("show", f"{revision}:{path}")


def working_tree_changed_paths() -> list[str]:
    tracked = subprocess.run(
        (
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--name-only",
            BASELINE_REVISION,
            "--",
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        (
            "git",
            "-c",
            "core.quotePath=false",
            "ls-files",
            "--others",
            "--exclude-standard",
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return sorted(set(tracked + untracked))


def acceptance_publication_revision(value: dict[str, Any]) -> str | None:
    commits = subprocess.run(
        (
            "git",
            "log",
            "--format=%H",
            "--diff-filter=A",
            "--",
            ACCEPTANCE_REPOSITORY_PATH,
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if not commits:
        return None
    if len(commits) != 1:
        raise ValueError("C2 acceptance receipt has multiple publication commits")
    revision = commits[0]
    receipt_path = REPOSITORY_ROOT / ACCEPTANCE_REPOSITORY_PATH
    if _git_file(revision, ACCEPTANCE_REPOSITORY_PATH) != receipt_path.read_bytes():
        raise ValueError("published C2 acceptance receipt was modified")
    if (
        subprocess.run(
            (
                "git",
                "merge-base",
                "--is-ancestor",
                value["source_revision"],
                revision,
            ),
            cwd=REPOSITORY_ROOT,
            check=False,
        ).returncode
        != 0
    ):
        raise ValueError("C2 publication revision is not based on its source baseline")
    return revision


def changed_paths(value: dict[str, Any], revision: str | None) -> list[str]:
    if revision is None:
        return working_tree_changed_paths()
    return subprocess.run(
        (
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--name-only",
            value["source_revision"],
            revision,
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()


def snapshot_file_bytes(path: str, revision: str | None) -> bytes:
    if revision is None:
        return (REPOSITORY_ROOT / path).read_bytes()
    return _git_file(revision, path)


def verify_focused_source_collection(focused: dict[str, Any]) -> None:
    environment = dict(os.environ)
    environment.update(FOCUSED_ENVIRONMENT)
    collection = subprocess.run(
        tuple(focused["collection_command"]),
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if collection.returncode != 0:
        raise ValueError("C2 focused test collection no longer succeeds")
    node_ids = [
        line.strip()
        for line in collection.stdout.splitlines()
        if "::" in line and not line.startswith("ERROR ")
    ]
    if (
        len(node_ids) != focused["node_count"]
        or len(node_ids) != len(set(node_ids))
        or digest_value(node_ids) != focused["node_ids_digest"]
    ):
        raise ValueError("C2 focused test node identity drifted")

    ruff = subprocess.run(
        tuple(focused["ruff_command"]),
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if (
        ruff.returncode != 0
        or digest_bytes(ruff.stdout.encode("utf-8"))
        != focused["ruff_stdout_digest"]
    ):
        raise ValueError("C2 focused Ruff result drifted")


def _snapshot_file_identity(path: str, revision: str | None) -> dict[str, Any]:
    if revision is None:
        source = REPOSITORY_ROOT / path
        if not source.exists():
            return {
                "path": path,
                "kind": "missing",
                "mode": None,
                "size": None,
                "digest": None,
            }
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"mainline source identity is not a regular file: {path}")
        content = source.read_bytes()
        mode = stat.S_IMODE(source.stat().st_mode)
    else:
        tree_entry = _git_output("ls-tree", revision, "--", path)
        if not tree_entry:
            return {
                "path": path,
                "kind": "missing",
                "mode": None,
                "size": None,
                "digest": None,
            }
        mode_text, object_kind, _ = tree_entry.split(maxsplit=2)
        if object_kind != "blob" or mode_text not in {"100644", "100755"}:
            raise ValueError(f"mainline source identity is not a regular file: {path}")
        content = _git_file(revision, path)
        mode = 0o755 if mode_text == "100755" else 0o644
    return {
        "path": path,
        "kind": "file",
        "mode": mode,
        "size": len(content),
        "digest": digest_bytes(content),
    }


def _verify_mainline_source_identity(
    value: dict[str, Any],
    *,
    revision: str | None,
    changed: list[str],
) -> None:
    mainline = value["mainline_validation"]
    source = mainline["source_identity"]
    if not isinstance(source, dict) or set(source) != {
        "commit",
        "tracked_diff_digest",
        "tracked_dirty_paths",
        "relevant_untracked_sources",
        "configurations",
        "locks",
        "toolchains",
    }:
        raise ValueError("C2 mainline source identity schema is not closed")
    if source["commit"] != BASELINE_REVISION:
        raise ValueError("C2 mainline source identity has the wrong baseline")
    if digest_value(source) != mainline["source_identity_digest"]:
        raise ValueError("C2 mainline source identity digest does not match")

    tracked_at_baseline = set(
        _git_output(
            "-c",
            "core.quotePath=false",
            "ls-tree",
            "-r",
            "--name-only",
            BASELINE_REVISION,
        ).splitlines()
    )
    expected_tracked = sorted(path for path in changed if path in tracked_at_baseline)
    if source["tracked_dirty_paths"] != expected_tracked:
        raise ValueError("C2 mainline tracked source set drifted")
    expected_untracked = sorted(
        path
        for path in changed
        if path not in tracked_at_baseline and path != ACCEPTANCE_REPOSITORY_PATH
    )
    observed_untracked = [item["path"] for item in source["relevant_untracked_sources"]]
    if observed_untracked != expected_untracked:
        raise ValueError("C2 mainline untracked source set drifted")

    diff_arguments = [
        "diff",
        "--binary",
        "--no-ext-diff",
        "--no-textconv",
        BASELINE_REVISION,
    ]
    if revision is not None:
        diff_arguments.append(revision)
    diff_arguments.extend(("--", *expected_tracked))
    if digest_bytes(_git_bytes(*diff_arguments)) != source["tracked_diff_digest"]:
        raise ValueError("C2 mainline tracked diff digest drifted")

    for group in ("relevant_untracked_sources", "configurations", "locks"):
        entries = source[group]
        if not isinstance(entries, list):
            raise ValueError(f"C2 mainline {group} is not a list")
        paths = [item["path"] for item in entries]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError(f"C2 mainline {group} paths are not sorted and unique")
        for item in entries:
            published_identity = _snapshot_file_identity(item["path"], revision)
            if item == published_identity:
                continue
            if (
                revision is not None
                and group == "locks"
                and published_identity["kind"] == "missing"
                and _snapshot_file_identity(item["path"], BASELINE_REVISION)["kind"]
                == "missing"
            ):
                continue
            raise ValueError(f"C2 mainline source identity drift: {item['path']}")
    if tuple(item["path"] for item in source["configurations"]) != (
        MAINLINE_CONFIGURATION_PATHS
    ):
        raise ValueError("C2 mainline configuration identity set drifted")
    if tuple(item["path"] for item in source["locks"]) != MAINLINE_LOCK_PATHS:
        raise ValueError("C2 mainline lock identity set drifted")
    toolchains = source["toolchains"]
    if not isinstance(toolchains, list) or [
        item.get("name") for item in toolchains if isinstance(item, dict)
    ] != ["python", "node", "uv", "npm"]:
        raise ValueError("C2 mainline toolchain identity set drifted")


def _published_revision(path: Path) -> str:
    repository_path = path.relative_to(REPOSITORY_ROOT).as_posix()
    commits = _git_output(
        "log",
        "--format=%H",
        "--diff-filter=A",
        "--",
        repository_path,
    ).splitlines()
    if len(commits) != 1:
        raise ValueError(f"acceptance receipt publication is not unique: {path}")
    published = subprocess.run(
        ("git", "show", f"{commits[0]}:{repository_path}"),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if published != path.read_bytes():
        raise ValueError(f"published acceptance receipt was modified: {path}")
    return commits[0]


def verify_prerequisites(binding: dict[str, Any]) -> None:
    if binding["change_id"] != CHANGE_ID:
        raise ValueError("prerequisite binding change id is invalid")
    if binding["source_revision"] != BASELINE_REVISION:
        raise ValueError("C2 source baseline revision drifted")
    if binding["status"] != "passed" or binding["external_effects"] != 0:
        raise ValueError("prerequisite binding did not close with zero effects")

    c0_verifier = _load_module(
        "c2_prerequisite_c0_verifier",
        C0_OPERATOR_DIR / "verify_supersession.py",
    )
    c1_verifier = _load_module(
        "c2_prerequisite_c1_verifier",
        C1_OPERATOR_DIR / "verify_repository_binding.py",
    )
    c0_result = c0_verifier.verify_all(
        require_acceptance=True,
        verify_sources=False,
    )
    c1_result = c1_verifier.verify_all(
        require_acceptance=True,
        verify_sources=True,
    )
    if c0_result["status"] != "passed" or c0_result["external_effects"] != 0:
        raise ValueError("C0 prerequisite verifier did not pass at zero effect")
    if (
        c1_result["status"] != "passed"
        or c1_result["upstream_effects"] != 0
        or c1_result["production_capability_lease_issuance_proven"] is not False
    ):
        raise ValueError("C1 prerequisite verifier crossed its product boundary")

    c0_path = C0_OPERATOR_DIR / "acceptance-receipt.json"
    c1_path = C1_OPERATOR_DIR / "acceptance-receipt.json"
    c0_receipt = load_json_object(c0_path)
    c1_receipt = load_json_object(c1_path)
    local_protocol = load_json_object(
        C1_OPERATOR_DIR / "local-protocol-acceptance-receipt.json"
    )
    expected_c0 = {
        "receipt_path": c0_path.relative_to(REPOSITORY_ROOT).as_posix(),
        "schema_id": "aox_artifact_cutover_supersession_acceptance@1",
        "receipt_digest": c0_receipt["receipt_digest"],
        "source_revision": c0_receipt["source_revision"],
        "publication_revision": _published_revision(c0_path),
        "manifest_digest": c0_receipt["manifest_digest"],
        "inventory_digest": c0_receipt["inventory_digest"],
        "legacy_decision": "legacy_no_go",
        "legacy_live_work_authorized": False,
        "legacy_identity_reusable": False,
        "verifier_command": (
            "uv run python openspec/changes/"
            "supersede-aox-hmm-artifact-cutover/operator/"
            "verify_supersession.py --require-acceptance"
        ),
    }
    if binding["c0"] != expected_c0:
        raise ValueError("C0 prerequisite binding drifted")
    source_is_ancestor = subprocess.run(
        (
            "git",
            "merge-base",
            "--is-ancestor",
            expected_c0["source_revision"],
            expected_c0["publication_revision"],
        ),
        cwd=REPOSITORY_ROOT,
        check=False,
    ).returncode
    if source_is_ancestor != 0:
        raise ValueError("C0 source revision is not an ancestor of its publication")

    credential_authority = local_protocol["credential_authority"]
    expected_c1 = {
        "receipt_path": c1_path.relative_to(REPOSITORY_ROOT).as_posix(),
        "schema_id": "project_repository_binding_acceptance@1",
        "receipt_digest": c1_receipt["receipt_digest"],
        "source_revision": c1_receipt["source_revision"],
        "publication_revision": c1_result["publication_revision"],
        "source_identity_digest": c1_receipt["mainline_validation"][
            "source_identity_digest"
        ],
        "implementation_tree_digest": c1_receipt["implementation_snapshot"][
            "tree_digest"
        ],
        "migration_id": c1_receipt["schema"]["migration_id"],
        "migration_sha256": c1_receipt["schema"]["migration_sha256"],
        "repository_policy_digest": c1_receipt["configuration"][
            "repository_policy_digest"
        ],
        "local_protocol_acceptance_digest": c1_receipt[
            "local_protocol_acceptance_digest"
        ],
        "lease_assertion_class": credential_authority["lease_assertion_class"],
        "production_capability_lease_issuance_proven": False,
        "verifier_command": (
            "uv run python openspec/changes/"
            "establish-project-repository-bindings/operator/"
            "verify_repository_binding.py --require-acceptance "
            "--verify-current-sources"
        ),
    }
    if binding["c1"] != expected_c1:
        raise ValueError("C1 prerequisite binding drifted")
    if (
        credential_authority["lease_assertion_class"] != "c1_acceptance_only"
        or credential_authority["production_capability_lease_issuance_proven"]
        is not False
        or c1_receipt["product_boundaries"][
            "production_capability_lease_issuance_proven"
        ]
        is not False
    ):
        raise ValueError("C1 acceptance-only authority was upgraded to production")
    baseline_parent = _git_output("rev-parse", f"{BASELINE_REVISION}^")
    if baseline_parent != expected_c1["publication_revision"]:
        raise ValueError("C2 source baseline is not the direct C1 verified successor")


def verify_authority_matrix(matrix: dict[str, Any]) -> None:
    if matrix["change_id"] != CHANGE_ID:
        raise ValueError("authority matrix change id is invalid")
    authorities = matrix["authorities"]
    authority_fields = {
        "authority_id",
        "canonical_owner",
        "lifecycle",
        "owns",
        "does_not_own",
    }
    if any(set(authority) != authority_fields for authority in authorities):
        raise ValueError("authority matrix rows are not closed")
    expected_ids = [
        "agent_capability_lease",
        "session_runtime_lease",
        "controlled_operation_execution",
        "mutation_writer",
        "approval_request",
        "scientific_attempt_authorization",
    ]
    if [authority["authority_id"] for authority in authorities] != expected_ids:
        raise ValueError("authority matrix owner set is incomplete or reordered")
    expected_owners = {
        "agent_capability_lease": "AgentCapabilityLease",
        "session_runtime_lease": "SessionRuntimeLease",
        "controlled_operation_execution": "ControlledOperationExecution",
        "mutation_writer": "MutationWriter",
        "approval_request": "ApprovalRequest",
        "scientific_attempt_authorization": "ScientificAttemptAuthorization",
    }
    expected_lifecycles = {
        "agent_capability_lease": ["pending_workspace", "active", "revoked"],
        "session_runtime_lease": [
            "acquired",
            "heartbeating",
            "released_or_expired",
        ],
        "controlled_operation_execution": [
            "awaiting_approval",
            "ready",
            "claimed",
            "dispatching",
            "waiting_external",
            "result_staging",
            "result_ready",
            "reconcile_required",
            "terminal",
        ],
        "mutation_writer": ["registered", "retiring", "retired", "rejected"],
        "approval_request": [
            "pending",
            "approved",
            "rejected",
            "expired",
            "cancelled",
        ],
        "scientific_attempt_authorization": [
            "active",
            "exhausted",
            "expired",
            "revoked",
        ],
    }
    for authority in authorities:
        authority_id = authority["authority_id"]
        if authority["canonical_owner"] != expected_owners[authority_id]:
            raise ValueError(f"canonical authority owner drifted: {authority_id}")
        if authority["lifecycle"] != expected_lifecycles[authority_id]:
            raise ValueError(f"authority lifecycle drifted: {authority_id}")
        if not authority["owns"] or not authority["does_not_own"]:
            raise ValueError(f"authority boundary is empty: {authority_id}")

    expected_pairs = [
        "session_runtime_lease",
        "controlled_operation_execution",
        "mutation_writer",
        "approval_request",
        "scientific_attempt_authorization",
    ]
    expected_cross_product = [
        {
            "left": "agent_capability_lease",
            "right": right,
            "relationship": "orthogonal",
            "substitution": "forbidden_both_directions",
        }
        for right in expected_pairs
    ]
    if matrix["cross_product"] != expected_cross_product:
        raise ValueError("authority cross-product permits substitution")
    if set(matrix["automatic_effects"]) != {
        "creates_controlled_operation_execution",
        "changes_controlled_operation_execution",
        "creates_mutation_writer",
        "resolves_or_reopens_approval",
        "creates_or_consumes_scientific_authorization",
        "changes_task_terminal_state",
    } or any(matrix["automatic_effects"].values()):
        raise ValueError("capability lease creates a forbidden automatic effect")
    expected_budget = {
        "scientific_ceiling_owner": "ScientificAttemptAuthorization",
        "scientific_ceilings": [
            "attempts",
            "micu",
            "cost_microunits",
            "wall_time_seconds",
        ],
        "mechanical_runtime_constraints": ["prompt", "context", "step"],
        "universal_budget_owner": None,
        "capability_lease_may_enlarge_budget": False,
        "budget_may_imply_capability_lease": False,
    }
    if matrix["budget_ownership"] != expected_budget:
        raise ValueError("authority matrix invents or transfers budget ownership")
    if matrix["publication_owner_present_in_c2"] is not False:
        raise ValueError("authority matrix invents a C2 publication owner")


def verify_policy(policy: dict[str, Any]) -> None:
    if policy["change_id"] != CHANGE_ID:
        raise ValueError("capability policy change id is invalid")
    if policy["policy_version"] != "agent-capability-policy-v1":
        raise ValueError("capability policy version drifted")
    from openzyme_core.agent_capability_service import (
        DEFAULT_AGENT_CAPABILITY_POLICY,
    )

    runtime_policy = DEFAULT_AGENT_CAPABILITY_POLICY
    if policy["lease_policy"] != runtime_policy.payload():
        raise ValueError("operator policy and runtime lease policy drifted")
    if policy["lease_policy_digest"] != runtime_policy.policy_digest:
        raise ValueError("operator policy and runtime lease policy digest drifted")
    if policy["profiles"] != {
        "general": GENERAL_CAPABILITIES,
        "executor": EXECUTOR_CAPABILITIES,
    }:
        raise ValueError("closed general/executor capability profiles drifted")
    if policy["role_profile_map"] != {
        "master": "general",
        "researcher": "general",
        "executor": "executor",
        "reporter": "general",
    }:
        raise ValueError("role/profile map drifted")
    if policy["allowed_child_profiles"] != {
        "executor": [],
        "master": ["general", "executor"],
        "reporter": [],
        "researcher": [],
    }:
        raise ValueError("allowed-child-profile map drifted")
    expected_targets = {
        "lease_target_ids": "explicit_sorted_unique_at_issuance",
        "safe_target_id_classes": [
            "internal_repository",
            "ordinary_network",
            "remote_hpc",
        ],
        "profile_target_classes": {
            "general": [
                "internal_repository",
                "ordinary_network",
            ],
            "executor": [
                "internal_repository",
                "ordinary_network",
                "remote_hpc",
            ],
        },
        "safe_projection": "identifier_or_digest_only",
        "private_locator_projected": False,
        "ordinary_network": {
            "runtime_owner": "C3_deployment",
            "host_destination_allowlist": False,
            "host_issued_credential_audience": "exact_service_target_protocol",
        },
        "remote_hpc_activation_owner": "deferred_remote_hpc_change",
    }
    if policy["target_scope_policy"] != expected_targets:
        raise ValueError("safe target-scope policy drifted")
    if policy["declaration_consumers"] != [
        "policy",
        "projection",
        "credential",
        "admission",
    ]:
        raise ValueError("C2 capability declaration consumer set drifted")
    false_fields = (
        "declaration_is_runtime_proof",
        "test_readiness_is_production_proof",
        "profile_fallback_allowed",
        "implicit_profile_escalation_allowed",
        "ambient_authority_inference_allowed",
    )
    if any(policy[field] is not False for field in false_fields):
        raise ValueError("capability policy permits proof inference or fallback")

    from openzyme_domain import AgentCapabilityProfile
    from openzyme_domain import capabilities_for_profile

    domain_profiles = {
        "general": [
            item.value
            for item in capabilities_for_profile(AgentCapabilityProfile.GENERAL)
        ],
        "executor": [
            item.value
            for item in capabilities_for_profile(AgentCapabilityProfile.EXECUTOR)
        ],
    }
    if policy["profiles"] != domain_profiles:
        raise ValueError("operator policy and domain closed profiles drifted")


def verify_scope_boundary(scope: dict[str, Any]) -> None:
    if scope["change_id"] != CHANGE_ID:
        raise ValueError("scope boundary change id is invalid")
    expected_c2_owns = [
        "workspace_generation_reservation_and_readiness_seam",
        "pending_active_revoked_capability_lease_control_plane",
        "closed_profile_target_and_delegation_policy",
        "credential_and_admission_typed_seams",
        "canonical_repository_credential_upgrade",
        "immediate_exact_generation_runtime_and_delegation_gate",
        "exact_bulk_subtree_revoke_and_retirement_freeze_completion",
        "safe_projection_and_typed_failure_contract",
    ]
    if scope["c2_owns"] != expected_c2_owns:
        raise ValueError("C2 owned scope drifted")
    if scope["staged_cutover"] != {
        "gate_effective_from": "C2_activation",
        "requires": "active_exact_generation_lease",
        "c3_not_ready_state": "provisioning_required",
        "c3_not_ready_runnable": False,
        "existing_agents_included": True,
        "new_agents_included": True,
        "delegated_child_initial_lease": "pending_workspace",
    }:
        raise ValueError("C2 staged cutover or non-runnable window drifted")
    expected_deferred = {
        "C3": {
            "change_id": "provision-independent-agent-git-workspaces",
            "owns": [
                "independent_git_workspace",
                "versioned_capsule_activation",
                "native_filesystem_shell_git_lfs_curl",
                "ordinary_deployment_network",
                "upload_download_runtime",
                "process_credential_injection",
                "production_workspace_readiness",
            ],
        },
        "C4": {
            "change_id": "publish-and-sync-workspace-revisions",
            "owns": [
                "workspace_publication_intent",
                "published_revision",
                "publication_ref_and_shared_truth",
            ],
        },
        "remote_hpc": {
            "change_id": "provision-isolated-executor-hpc-workspaces",
            "owns": [
                "real_target_scoped_ssh_credential",
                "remote_login_workspace_crud",
                "target_os_and_root_isolation",
                "native_remote_transfer_proof",
            ],
        },
        "job": {
            "change_id": "execute-hpc-jobs-from-workspace-revisions",
            "owns": [
                "approval_free_ordinary_job_admission",
                "target_side_submit_guard",
                "one_occurrence_sbatch_credential",
            ],
        },
    }
    if scope["deferred_owners"] != expected_deferred:
        raise ValueError("deferred C3/C4/remote-HPC/job ownership drifted")
    if scope["deferred_false_claims"] != DEFERRED_FALSE_CLAIMS:
        raise ValueError("scope boundary overclaims a deferred production proof")
    if scope["test_readiness"] != {
        "explicit_test_provider_allowed": True,
        "production_workspace_proof": False,
        "production_capsule_activation_proof": False,
        "may_clear_production_provisioning_required": False,
    }:
        raise ValueError("test readiness was promoted to production proof")
    expected_fallbacks = [
        "legacy_sandbox",
        "legacy_process",
        "parent_capsule",
        "parent_workspace",
        "parent_or_other_agent_credential",
        "local_execution_substitution",
        "route_workspace_or_endpoint_switch",
        "profile_downgrade_or_upgrade",
        "automatic_retry_or_command_replay",
    ]
    if scope["forbidden_fallbacks"] != expected_fallbacks:
        raise ValueError("forbidden fallback set drifted")
    if scope["legacy_execution_noninterference"] != {
        "host_supervised_execution_unchanged": True,
        "aox_network_none_unchanged": True,
        "may_satisfy_capability_gate": False,
        "may_act_as_fallback": False,
    }:
        raise ValueError("legacy execution was changed or used as a fallback")
    if scope["operator_effects"] != {
        "live_authorized": False,
        "provider_requests": 0,
        "hpc_connections": 0,
        "scheduler_submissions": 0,
        "external_effects": 0,
    }:
        raise ValueError("operator scope authorizes an external effect")
    if scope["eligible_successor"] != {
        "short_name": "C3",
        "change_id": "provision-independent-agent-git-workspaces",
        "eligible_only_after_c2_acceptance": True,
        "production_readiness_owner": True,
    }:
        raise ValueError("C3 successor boundary drifted")


def verify_tasks() -> int:
    text = C2_TASKS_PATH.read_text(encoding="utf-8")
    complete = re.findall(r"^- \[x\] (\d+\.\d+) ", text, flags=re.MULTILINE)
    pending = re.findall(r"^- \[ \] (\d+\.\d+) ", text, flags=re.MULTILINE)
    expected = [f"{group}.{item}" for group in range(1, 7) for item in range(1, 7)]
    if pending:
        raise ValueError(f"C2 task checklist remains incomplete: {pending}")
    if complete != expected:
        raise ValueError("C2 task checklist is incomplete, duplicated, or reordered")
    return len(complete)


def _verify_digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} is not a canonical digest")


def _verify_mainline_evidence(mainline: dict[str, Any]) -> None:
    expected_fields = {
        "status",
        "command",
        "verification_command",
        "profile_id",
        "authority_domain",
        "current_authoritative_entry",
        "plan_digest",
        "receipt_digest",
        "source_identity_digest",
        "source_identity",
        "plan_schema_id",
        "receipt_schema_id",
        "receipt_plan_digest",
        "receipt_source_identity_digest",
        "verification_result",
        "plan",
        "receipt",
        "terminal_status",
        "authoritative",
        "profile_contract_authoritative",
        "admission_eligible",
        "live_eligible",
        "verified_current_sources",
    }
    if set(mainline) != expected_fields:
        raise ValueError("C2 mainline evidence schema is not closed")
    expected_values = {
        "status": "passed",
        "command": "./scripts/check-mainline.sh",
        "verification_command": "verify-mainline-authoritative",
        "profile_id": "mainline_authoritative",
        "authority_domain": "authoritative_non_live_mainline",
        "current_authoritative_entry": "scripts/check-mainline.sh",
        "plan_schema_id": "openzyme_test_execution_plan@1",
        "receipt_schema_id": "openzyme_test_gate_receipt@1",
        "terminal_status": "pass",
        "authoritative": True,
        "profile_contract_authoritative": True,
        "admission_eligible": False,
        "live_eligible": False,
        "verified_current_sources": True,
    }
    for field, expected in expected_values.items():
        if mainline[field] != expected:
            raise ValueError(f"C2 mainline authority drifted: {field}")
    for field in ("plan_digest", "receipt_digest", "source_identity_digest"):
        _verify_digest(mainline[field], f"mainline {field}")
    source_identity = mainline["source_identity"]
    if not isinstance(source_identity, dict) or set(source_identity) != {
        "commit",
        "tracked_diff_digest",
        "tracked_dirty_paths",
        "relevant_untracked_sources",
        "configurations",
        "locks",
        "toolchains",
    }:
        raise ValueError("C2 mainline source identity schema is not closed")
    if source_identity["commit"] != BASELINE_REVISION:
        raise ValueError("C2 mainline source identity has the wrong baseline")
    if mainline["source_identity_digest"] != digest_value(source_identity):
        raise ValueError("C2 mainline source identity seal is invalid")
    if tuple(item.get("path") for item in source_identity["configurations"]) != (
        MAINLINE_CONFIGURATION_PATHS
    ):
        raise ValueError("C2 mainline configuration identity set drifted")
    if tuple(item.get("path") for item in source_identity["locks"]) != (
        MAINLINE_LOCK_PATHS
    ):
        raise ValueError("C2 mainline lock identity set drifted")
    toolchains = source_identity["toolchains"]
    if not isinstance(toolchains, list) or [
        item.get("name") for item in toolchains if isinstance(item, dict)
    ] != ["python", "node", "uv", "npm"]:
        raise ValueError("C2 mainline toolchain identity set drifted")
    if any(
        not isinstance(item, dict)
        or set(item) != {"available", "executable", "name", "version"}
        or item["available"] is not True
        or not isinstance(item["executable"], str)
        or not item["executable"]
        or not isinstance(item["version"], str)
        or not item["version"]
        for item in toolchains
    ):
        raise ValueError("C2 mainline toolchain identity schema drifted")
    if mainline["receipt_plan_digest"] != mainline["plan_digest"]:
        raise ValueError("C2 mainline receipt does not bind the exact plan")
    if (
        mainline["receipt_source_identity_digest"]
        != mainline["source_identity_digest"]
    ):
        raise ValueError("C2 mainline receipt source identity drifted")

    verification_result = mainline["verification_result"]
    expected_verification_fields = {
        "profile_id",
        "output_root",
        "plan_digest",
        "receipt_digest",
        "terminal_status",
        "valid",
        "authoritative",
        "profile_contract_authoritative",
        "admission_eligible",
        "live_eligible",
        "authority_domain",
        "current_authoritative_entry",
    }
    if (
        not isinstance(verification_result, dict)
        or set(verification_result) != expected_verification_fields
    ):
        raise ValueError("C2 official mainline verification schema is not closed")
    expected_verification = {
        "profile_id": "mainline_authoritative",
        "output_root": verification_result["output_root"],
        "plan_digest": mainline["plan_digest"],
        "receipt_digest": mainline["receipt_digest"],
        "terminal_status": "pass",
        "valid": True,
        "authoritative": True,
        "profile_contract_authoritative": True,
        "admission_eligible": False,
        "live_eligible": False,
        "authority_domain": "authoritative_non_live_mainline",
        "current_authoritative_entry": "scripts/check-mainline.sh",
    }
    if verification_result != expected_verification:
        raise ValueError("C2 official mainline verification result drifted")
    output_root = verification_result["output_root"]
    if not isinstance(output_root, str) or not Path(output_root).is_absolute():
        raise ValueError("C2 official mainline output root is invalid")

    plan = mainline["plan"]
    expected_plan_fields = {
        "authority",
        "collections",
        "config_digest",
        "expected_coverage_digest",
        "invocation_id",
        "legacy_execution_multiset_digest",
        "node_ownership",
        "output_root",
        "planner_digest",
        "profile_id",
        "schema_id",
        "self_digest",
        "source_identity",
        "source_recheck_policy",
        "stages",
        "toolchains",
        "worker_policy",
    }
    if not isinstance(plan, dict) or set(plan) != expected_plan_fields:
        raise ValueError("C2 authoritative mainline plan schema is not closed")
    plan_preimage = {key: item for key, item in plan.items() if key != "self_digest"}
    if plan["self_digest"] != digest_value(plan_preimage):
        raise ValueError("C2 authoritative mainline plan seal is invalid")
    if (
        plan["self_digest"] != mainline["plan_digest"]
        or plan["schema_id"] != mainline["plan_schema_id"]
        or plan["profile_id"] != "mainline_authoritative"
        or plan["source_identity"] != mainline["source_identity"]
        or plan["toolchains"] != mainline["source_identity"]["toolchains"]
        or plan["output_root"] != output_root
    ):
        raise ValueError("C2 authoritative mainline plan binding drifted")
    if plan["authority"] != {
        "admission_eligible": False,
        "authoritative": True,
        "authority_domain": "authoritative_non_live_mainline",
        "current_authoritative_entry": "scripts/check-mainline.sh",
        "live_eligible": False,
        "profile_contract_authoritative": True,
    }:
        raise ValueError("C2 authoritative mainline plan authority drifted")

    mainline_receipt = mainline["receipt"]
    expected_receipt_fields = {
        "admission_eligible",
        "authoritative",
        "coverage",
        "frontend",
        "invocation_id",
        "live_eligible",
        "plan_digest",
        "profile_id",
        "qualification",
        "resource_assignments",
        "schema_id",
        "self_digest",
        "source_identity_digest",
        "stages",
        "terminal_status",
        "timing",
    }
    if (
        not isinstance(mainline_receipt, dict)
        or set(mainline_receipt) != expected_receipt_fields
    ):
        raise ValueError("C2 authoritative mainline receipt schema is not closed")
    receipt_preimage = {
        key: item for key, item in mainline_receipt.items() if key != "self_digest"
    }
    if mainline_receipt["self_digest"] != digest_value(receipt_preimage):
        raise ValueError("C2 authoritative mainline receipt seal is invalid")
    expected_receipt_bindings = {
        "schema_id": mainline["receipt_schema_id"],
        "self_digest": mainline["receipt_digest"],
        "plan_digest": mainline["plan_digest"],
        "source_identity_digest": mainline["source_identity_digest"],
        "profile_id": "mainline_authoritative",
        "terminal_status": "pass",
        "authoritative": True,
        "admission_eligible": False,
        "live_eligible": False,
    }
    for field, expected in expected_receipt_bindings.items():
        if mainline_receipt[field] != expected:
            raise ValueError(
                f"C2 authoritative mainline receipt binding drifted: {field}"
            )
    if mainline_receipt["invocation_id"] != plan["invocation_id"]:
        raise ValueError("C2 authoritative mainline invocation identity drifted")


def _verify_evidence_sections(
    value: dict[str, Any],
    *,
    verify_sources: bool,
) -> None:
    source_revision = value["source_revision"]
    if source_revision != BASELINE_REVISION:
        raise ValueError("C2 source revision is not the exact C1-derived baseline")

    snapshot = value["implementation_snapshot"]
    if set(snapshot) != {"file_count", "files", "tree_digest"}:
        raise ValueError("C2 implementation snapshot schema is not closed")
    entries = snapshot["files"]
    if snapshot["file_count"] != len(entries) or snapshot["tree_digest"] != digest_value(
        entries
    ):
        raise ValueError("C2 implementation snapshot digest or count drifted")
    paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
    if len(paths) != len(entries) or paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError("C2 implementation paths are not sorted and unique")
    for entry in entries:
        if set(entry) != {"path", "size", "sha256"}:
            raise ValueError("C2 implementation entry schema is not closed")
        _verify_digest(entry["sha256"], f"implementation digest: {entry['path']}")
        if not isinstance(entry["size"], int) or isinstance(entry["size"], bool):
            raise ValueError(f"implementation size is invalid: {entry['path']}")
        path = Path(entry["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"implementation path is unsafe: {entry['path']}")

    schema = value["schema"]
    if set(schema) != {
        "sqlite_schema_before",
        "sqlite_schema_after",
        "migration_id",
        "migration_sha256",
        "lease_schema",
        "generation_reservation_schema",
        "retirement_request_schema",
        "retirement_cleanup_proof_schema",
        "retirement_schema",
    }:
        raise ValueError("C2 schema evidence is not closed")
    expected_schema = {
        "sqlite_schema_before": 38,
        "sqlite_schema_after": 39,
        "migration_id": "039_v3_agent_capability_leases",
        "migration_sha256": digest_bytes(
            (REPOSITORY_ROOT / MIGRATION_PATH).read_bytes()
        ),
        "lease_schema": "agent_capability_lease@1",
        "generation_reservation_schema": (
            "agent_workspace_generation_reservation@1"
        ),
        "retirement_request_schema": "agent_retirement_request@1",
        "retirement_cleanup_proof_schema": (
            "agent_retirement_cleanup_proof@1"
        ),
        "retirement_schema": "agent_retirement_record@1",
    }
    if schema != expected_schema:
        raise ValueError("C2 schema or migration identity drifted")

    focused = value["focused_validation"]
    if set(focused) != {
        "status",
        "test_files",
        "collection_command",
        "collection_exit_code",
        "node_count",
        "node_ids_digest",
        "collection_stdout_digest",
        "pytest_command",
        "pytest_exit_code",
        "pytest_stdout_digest",
        "passed",
        "failed",
        "errors",
        "skipped",
        "ruff_command",
        "ruff_exit_code",
        "ruff_stdout_digest",
        "ruff_status",
        "environment",
        "source_tree_digest",
        "live_provider_hpc_opt_in",
    }:
        raise ValueError("C2 focused validation evidence is not closed")
    expected_collection_command = [
        FOCUSED_PYTHON,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-p",
        "no:cacheprovider",
        *FOCUSED_TEST_FILES,
    ]
    expected_pytest_prefix = [
        FOCUSED_PYTHON,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    pytest_command = focused["pytest_command"]
    if (
        not isinstance(pytest_command, list)
        or len(pytest_command) != len(expected_pytest_prefix) + 1 + len(FOCUSED_TEST_FILES)
        or pytest_command[: len(expected_pytest_prefix)] != expected_pytest_prefix
        or not isinstance(pytest_command[len(expected_pytest_prefix)], str)
        or not pytest_command[len(expected_pytest_prefix)].startswith(
            "--junitxml=/tmp/openzyme-c2-focused-"
        )
        or not pytest_command[len(expected_pytest_prefix)].endswith(
            "/focused-junit.xml"
        )
        or pytest_command[len(expected_pytest_prefix) + 1 :]
        != list(FOCUSED_TEST_FILES)
    ):
        raise ValueError("C2 focused pytest command drifted")
    for digest_field in (
        "node_ids_digest",
        "collection_stdout_digest",
        "pytest_stdout_digest",
        "ruff_stdout_digest",
        "source_tree_digest",
    ):
        _verify_digest(focused[digest_field], f"focused {digest_field}")
    if (
        focused["status"] != "passed"
        or tuple(focused["test_files"]) != FOCUSED_TEST_FILES
        or focused["collection_command"] != expected_collection_command
        or focused["collection_exit_code"] != 0
        or not isinstance(focused["node_count"], int)
        or isinstance(focused["node_count"], bool)
        or focused["node_count"] <= 0
        or focused["pytest_exit_code"] != 0
        or not isinstance(focused["passed"], int)
        or isinstance(focused["passed"], bool)
        or focused["passed"] != focused["node_count"]
        or focused["failed"] != 0
        or focused["errors"] != 0
        or focused["skipped"] != 0
        or focused["ruff_command"]
        != [FOCUSED_PYTHON, "-m", "ruff", "check", *FOCUSED_RUFF_PATHS]
        or focused["ruff_exit_code"] != 0
        or focused["ruff_stdout_digest"]
        != digest_bytes(b"All checks passed!\n")
        or focused["ruff_status"] != "passed"
        or focused["environment"] != FOCUSED_ENVIRONMENT
        or focused["source_tree_digest"] != snapshot["tree_digest"]
        or focused["live_provider_hpc_opt_in"] is not False
    ):
        raise ValueError("C2 focused validation did not close")

    if value["documentation"] != {
        "status": "passed",
        "paths": list(DOCUMENTATION_PATHS),
    }:
        raise ValueError("C2 documentation evidence is incomplete")
    if value["openspec_validation"] != {
        "status": "passed",
        "command": (
            "DO_NOT_TRACK=1 openspec validate establish-agent-capability-leases "
            "--type change --strict --no-interactive"
        ),
        "result": "Change 'establish-agent-capability-leases' is valid",
    }:
        raise ValueError("C2 strict OpenSpec evidence drifted")

    _verify_mainline_evidence(value["mainline_validation"])

    audit = value["scope_audit"]
    if set(audit) != {
        "status",
        "changed_path_count",
        "changed_path_set_digest",
        "implementation_manifest_digest",
        "forbidden_changed_paths",
        "ast_policy_digest",
        "audited_production_paths",
        "audited_production_path_digest",
        "forbidden_findings",
    }:
        raise ValueError("C2 scope audit evidence is not closed")
    _verify_digest(audit["changed_path_set_digest"], "scope changed-path digest")
    expected_scope_paths = sorted(
        [*EXPECTED_IMPLEMENTATION_PATHS, ACCEPTANCE_REPOSITORY_PATH]
    )
    expected_production_paths = sorted(
        path
        for path in EXPECTED_IMPLEMENTATION_PATHS
        if path.endswith(".py")
        and any(path.startswith(prefix) for prefix in PRODUCTION_SOURCE_PREFIXES)
    )
    if (
        audit["status"] != "passed"
        or audit["changed_path_count"] != len(expected_scope_paths)
        or audit["changed_path_set_digest"] != digest_value(expected_scope_paths)
        or audit["implementation_manifest_digest"]
        != digest_value(list(EXPECTED_IMPLEMENTATION_PATHS))
        or audit["forbidden_changed_paths"] != []
        or audit["ast_policy_digest"] != digest_value(deferred_ast_policy())
        or audit["audited_production_paths"] != expected_production_paths
        or audit["audited_production_path_digest"]
        != digest_value(expected_production_paths)
        or audit["forbidden_findings"] != []
    ):
        raise ValueError("C2 scope audit did not close")
    if not isinstance(value["issued_at"], str) or not value["issued_at"]:
        raise ValueError("C2 evidence issued_at is missing")
    if verify_sources:
        publication_revision = verify_snapshot(value)
        if (
            publication_revision is None
            or _git_output("rev-parse", "HEAD") == publication_revision
        ):
            verify_focused_source_collection(focused)


def verify_snapshot(value: dict[str, Any]) -> str | None:
    revision = acceptance_publication_revision(value)
    observed_paths = changed_paths(value, revision)
    scope_paths = sorted(set([*observed_paths, ACCEPTANCE_REPOSITORY_PATH]))
    expected_scope_paths = sorted(
        [*EXPECTED_IMPLEMENTATION_PATHS, ACCEPTANCE_REPOSITORY_PATH]
    )
    if scope_paths != expected_scope_paths:
        raise ValueError("C2 changed paths do not equal the reviewed implementation manifest")
    forbidden = [
        path
        for path in scope_paths
        if not is_allowed_scope_path(path)
    ]
    if forbidden:
        raise ValueError(f"C2 changed forbidden paths: {forbidden}")
    _verify_mainline_source_identity(
        value,
        revision=revision,
        changed=scope_paths,
    )

    audit = value["scope_audit"]
    if audit["changed_path_count"] != len(scope_paths):
        raise ValueError("C2 scope audit path count does not match")
    if audit["changed_path_set_digest"] != digest_value(scope_paths):
        raise ValueError("C2 scope audit path digest does not match")
    if audit["forbidden_changed_paths"] != []:
        raise ValueError("C2 scope audit reports forbidden paths")
    boundary = verify_deferred_implementation_boundary(
        list(EXPECTED_IMPLEMENTATION_PATHS),
        revision=revision,
    )
    for field, expected in boundary.items():
        if audit[field] != expected:
            raise ValueError(f"C2 deferred implementation audit drifted: {field}")

    entries = value["implementation_snapshot"]["files"]
    manifest_paths = [entry["path"] for entry in entries]
    expected_implementation_paths = [
        path for path in scope_paths if path != ACCEPTANCE_REPOSITORY_PATH
    ]
    if manifest_paths != expected_implementation_paths:
        raise ValueError(
            "C2 implementation snapshot does not cover the exact change scope"
        )
    for entry in entries:
        content = snapshot_file_bytes(entry["path"], revision)
        if digest_bytes(content) != entry["sha256"] or len(content) != entry["size"]:
            raise ValueError(f"C2 implementation snapshot drift: {entry['path']}")
    return revision


def verify_final_evidence(
    evidence: dict[str, Any],
    *,
    verify_sources: bool,
) -> str:
    if set(evidence) != FINAL_EVIDENCE_FIELDS:
        raise ValueError("C2 final evidence fields are not closed")
    if evidence["schema_id"] != FINAL_EVIDENCE_SCHEMA:
        raise ValueError("C2 final evidence schema identity is invalid")
    preimage = {
        key: item for key, item in evidence.items() if key != "evidence_digest"
    }
    expected_digest = digest_value(preimage)
    if evidence["evidence_digest"] != expected_digest:
        raise ValueError("C2 final evidence canonical digest does not match")
    _verify_evidence_sections(evidence, verify_sources=verify_sources)
    return expected_digest


def verify_acceptance(
    receipt: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    document_digests: dict[str, str],
    *,
    verify_sources: bool,
) -> None:
    expected_bindings = {
        "c0_acceptance_receipt_digest": documents["prerequisites"]["c0"][
            "receipt_digest"
        ],
        "c1_acceptance_receipt_digest": documents["prerequisites"]["c1"][
            "receipt_digest"
        ],
        "prerequisite_bindings_digest": document_digests["prerequisites"],
        "authority_matrix_digest": document_digests["authority_matrix"],
        "capability_policy_document_digest": document_digests["policy"],
        "capability_policy_digest": documents["policy"]["lease_policy_digest"],
        "scope_boundary_digest": document_digests["scope_boundary"],
    }
    for field, expected in expected_bindings.items():
        if receipt[field] != expected:
            raise ValueError(f"C2 acceptance binding drifted: {field}")
    final_evidence_preimage = {
        "schema_id": FINAL_EVIDENCE_SCHEMA,
        "source_revision": receipt["source_revision"],
        "implementation_snapshot": receipt["implementation_snapshot"],
        "schema": receipt["schema"],
        "focused_validation": receipt["focused_validation"],
        "documentation": receipt["documentation"],
        "openspec_validation": receipt["openspec_validation"],
        "mainline_validation": receipt["mainline_validation"],
        "scope_audit": receipt["scope_audit"],
        "issued_at": receipt["issued_at"],
    }
    expected_evidence_digest = digest_value(final_evidence_preimage)
    if receipt["final_evidence_digest"] != expected_evidence_digest:
        raise ValueError("C2 acceptance does not bind its reconstructed final evidence")
    _verify_evidence_sections(receipt, verify_sources=verify_sources)
    if receipt["change_id"] != CHANGE_ID or receipt["status"] != "passed":
        raise ValueError("C2 acceptance receipt did not pass")
    if receipt["deferred_false_claims"] != DEFERRED_FALSE_CLAIMS:
        raise ValueError("C2 acceptance overclaims a deferred production proof")
    if receipt["test_readiness_is_production_proof"] is not False:
        raise ValueError("C2 acceptance promotes test readiness to production proof")
    if receipt["eligible_successor"] != {
        "short_name": "C3",
        "change_id": "provision-independent-agent-git-workspaces",
        "eligible_now": True,
    }:
        raise ValueError("C2 acceptance successor identity drifted")


def verify_all(
    *,
    require_acceptance: bool,
    verify_sources: bool,
) -> dict[str, Any]:
    if verify_sources and not require_acceptance:
        raise ValueError("current source verification requires final C2 acceptance")
    names = ["prerequisites", "authority_matrix", "policy", "scope_boundary"]
    if require_acceptance:
        names.append("acceptance")
    loaded = {name: load_document(name) for name in names}
    documents = {name: value for name, value in loaded.items() if value is not None}
    digests = {name: verify_document(name, value) for name, value in documents.items()}
    verify_prerequisites(documents["prerequisites"])
    verify_authority_matrix(documents["authority_matrix"])
    verify_policy(documents["policy"])
    verify_scope_boundary(documents["scope_boundary"])
    completed_tasks = 0
    publication = None
    if require_acceptance:
        completed_tasks = verify_tasks()
        verify_acceptance(
            documents["acceptance"],
            documents,
            digests,
            verify_sources=verify_sources,
        )
        if verify_sources:
            publication = acceptance_publication_revision(documents["acceptance"])
    return {
        "schema_id": "agent_capability_lease_verification@1",
        "status": "passed",
        "acceptance_required": require_acceptance,
        "sources_verified": verify_sources,
        "publication_revision": publication,
        "completed_tasks": completed_tasks,
        "document_digests": digests,
        "deferred_false_claims": DEFERRED_FALSE_CLAIMS,
        "test_readiness_is_production_proof": False,
        "eligible_successor": "C3_after_acceptance",
        "external_effects": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-acceptance",
        action="store_true",
        help="also require and verify the final C2 acceptance receipt",
    )
    parser.add_argument(
        "--verify-current-sources",
        action="store_true",
        help="verify the exact source snapshot bound by final acceptance",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    result = verify_all(
        require_acceptance=arguments.require_acceptance,
        verify_sources=arguments.verify_current_sources,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
