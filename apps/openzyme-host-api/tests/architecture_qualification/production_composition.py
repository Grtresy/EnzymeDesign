from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[4]
_SENSITIVE_ENV_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "OPENAI_API_KEY",
        "OPENZYME_AOX_LIVE_ENABLED",
        "OPENZYME_LIVE_E2E_ENABLED",
        "TAVILY_API_KEY",
    }
)


@dataclass(frozen=True, slots=True)
class ProductionCompositionReceipt:
    suite_id: str
    command: tuple[str, ...]
    returncode: int
    duration_milliseconds: int
    stdout_digest: str
    stderr_digest: str
    stdout_bytes: int
    stderr_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "command": list(self.command),
            "duration_milliseconds": self.duration_milliseconds,
            "returncode": self.returncode,
            "stderr_bytes": self.stderr_bytes,
            "stderr_digest": self.stderr_digest,
            "stdout_bytes": self.stdout_bytes,
            "stdout_digest": self.stdout_digest,
            "suite_id": self.suite_id,
        }


_PYTEST_SELECTIONS: dict[str, tuple[str, ...]] = {
    "capability-affordance": (
        "packages/openzyme-kernel/tests/test_affordance.py",
        "packages/openzyme-hpc/tests/test_inventory.py",
        "packages/openzyme-hpc/tests/test_qualification.py",
        "packages/openzyme-hpc/tests/test_routes.py",
    ),
    "deployment-proof": (
        "packages/openzyme-store-sqlite/tests/test_deployment_proof.py",
        "packages/openzyme-store-sqlite/tests/test_offline_cutover_contract.py",
        "packages/openzyme-store-sqlite/tests/test_offline_cutover_planning.py",
    ),
    "diagnostic-publication-cleanup": (
        "packages/openzyme-kernel/tests/test_composition_diagnostics.py",
        "packages/openzyme-kernel/tests/test_workspace_operations.py::test_unclassified_adapter_failure_preserves_cause_after_reconcile_record",
        "packages/openzyme-kernel/tests/test_publication_application.py::test_publication_response_loss_reconciles_without_redispatch",
        "packages/openzyme-kernel/tests/test_publication_application.py::test_pending_publication_reconciliation_never_redispatches",
        "packages/openzyme-kernel/tests/test_publication_application.py::test_publication_reconciles_original_uncertain_effect_after_revoke",
        "packages/openzyme-process-podman/tests/test_container_lifecycle.py",
    ),
    "enzymedesign-catalog": (
        "packages/enzymedesign-distribution/tests/test_distribution.py",
        "-k",
        "not test_real_product_composition_runs_hmmer_and_vina_through_one_pinned_graph",
        "packages/enzymedesign-hmmer/tests/test_hmmer_plugin.py",
        "packages/openzyme-hpc/tests/test_component_manifest.py",
        "packages/openzyme-hpc/tests/test_workspace_tools.py",
    ),
    "enzymedesign-product-cross-layer": (
        "packages/enzymedesign-distribution/tests/test_distribution.py::"
        "test_real_product_composition_runs_hmmer_and_vina_through_one_pinned_graph",
    ),
    "kernel-fake-adapters": (
        "packages/openzyme-kernel/tests/test_testing_fakes.py",
        "packages/openzyme-kernel/tests/test_authority_application.py",
        "packages/openzyme-kernel/tests/test_controlled_operation_application.py",
        "packages/openzyme-kernel/tests/test_workspace_operations.py",
    ),
    "owner-source-document": (
        "packages/openzyme-kernel/tests/test_architecture_manifests.py",
        "packages/openzyme-kernel/tests/test_architecture_inventory.py",
        "packages/openzyme-kernel/tests/test_wheel_qualification_profiles.py",
    ),
    "plugin-negative": (
        "packages/openzyme-kernel/tests/test_composition.py",
        "packages/openzyme-kernel/tests/test_activation.py",
        "packages/openzyme-kernel/tests/test_extension_mount.py",
        "packages/openzyme-kernel/tests/test_session_composition.py",
    ),
    "scientific-finalization": (
        "packages/openzyme-science/tests/test_science_plugin.py",
        "packages/openzyme-science/tests/test_sqlite_transaction_integration.py",
        "packages/enzymedesign-aox/tests/test_file_bundle_finalizer.py",
    ),
    "workspace-job": (
        "apps/mcp-hpc-runner/tests/test_workspace_revision_job_wire.py",
        "packages/openzyme-compute/tests/test_compute_lifecycle.py",
        "packages/openzyme-hpc-slurm/tests/test_scheduler_adapter.py",
    ),
    "workspace-runtime": (
        "packages/openzyme-kernel/tests/test_workspace_operations.py",
        "packages/openzyme-kernel/tests/test_workspace_tools.py",
        "packages/openzyme-process-podman/tests/test_filesystem_adapter.py",
        "packages/openzyme-process-podman/tests/test_process_adapter.py",
        "packages/openzyme-hpc/tests/test_workspace_lifecycle.py",
        "packages/openzyme-hpc/tests/test_workspace_state_machine.py",
    ),
    "standard-composition": (
        "packages/openzyme-standard/tests/test_composition.py",
        "packages/openzyme-standard/tests/test_host_gateway.py",
        "packages/openzyme-standard/tests/test_message_ingress_sqlite.py",
        "packages/openzyme-standard/tests/test_standard_v2_host.py",
        "packages/openzyme-store-sqlite/tests/test_composite_startup.py",
        "packages/openzyme-store-sqlite/tests/test_deployment_proof.py",
        "packages/openzyme-store-sqlite/tests/test_evidence_publication_entity_codecs.py",
        "packages/openzyme-store-sqlite/tests/test_kernel_command_receipt_codec.py",
        "packages/openzyme-workspace-git-lfs/tests/test_agent_workspaces.py",
        "packages/openzyme-workspace-git-lfs/tests/test_revision_backend.py",
        "packages/openzyme-client/tests/test_v2_client.py",
    ),
}


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _non_live_environment(*, runner_sources: bool) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in _SENSITIVE_ENV_NAMES
    }
    environment.update(
        {
            "NO_PROXY": "*",
            "OPENZYME_ALLOW_LIVE": "0",
            "OPENZYME_ARCHITECTURE_QUALIFICATION_CHILD": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    environment.update({name: "" for name in _SENSITIVE_ENV_NAMES})
    python_paths = [str(REPO_ROOT / "apps/openzyme-host-api/tests")]
    if runner_sources:
        python_paths.append(str(REPO_ROOT / "apps/mcp-hpc-runner/src"))
    existing = environment.get("PYTHONPATH")
    if existing:
        python_paths.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    return environment


def run_closed_non_live_suite(suite_id: str) -> ProductionCompositionReceipt:
    if suite_id == "web-ui":
        command = ("npm", "test")
        cwd = REPO_ROOT / "apps/openzyme-web-ui"
        runner_sources = False
        timeout_seconds = 45
    elif suite_id == "wheel-installation":
        command = (sys.executable, "scripts/qualify-openzyme-contract-wheels.py")
        cwd = REPO_ROOT
        runner_sources = False
        timeout_seconds = 180
    else:
        selectors = _PYTEST_SELECTIONS.get(suite_id)
        if selectors is None:
            raise ValueError(f"unknown production composition suite {suite_id!r}")
        command = (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "architecture_qualification.no_live_effects",
            *selectors,
        )
        cwd = REPO_ROOT
        runner_sources = suite_id == "workspace-job"
        timeout_seconds = 45
    started = time.monotonic_ns()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=_non_live_environment(runner_sources=runner_sources),
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AssertionError(
            "production composition process failed before a complete receipt: "
            f"suite={suite_id} phase=spawn_or_wait cause={type(exc).__name__}: {exc}"
        ) from exc
    duration = max(0, (time.monotonic_ns() - started) // 1_000_000)
    receipt = ProductionCompositionReceipt(
        suite_id=suite_id,
        command=command,
        returncode=result.returncode,
        duration_milliseconds=duration,
        stdout_digest=_sha256(result.stdout),
        stderr_digest=_sha256(result.stderr),
        stdout_bytes=len(result.stdout),
        stderr_bytes=len(result.stderr),
    )
    if result.returncode != 0:
        stdout_tail = result.stdout.decode("utf-8", errors="replace")[-2_000:]
        stderr_tail = result.stderr.decode("utf-8", errors="replace")[-2_000:]
        raise AssertionError(
            "production composition suite failed: "
            f"receipt={receipt.to_dict()} stdout_tail={stdout_tail!r} "
            f"stderr_tail={stderr_tail!r}"
        )
    return receipt


__all__ = ["ProductionCompositionReceipt", "run_closed_non_live_suite"]
