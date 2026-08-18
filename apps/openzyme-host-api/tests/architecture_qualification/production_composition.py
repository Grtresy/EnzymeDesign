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
    "deployment-proof": (
        "packages/openzyme-core/tests/test_migrations.py",
        "packages/openzyme-core/tests/test_offline_removal_fixture.py::test_partial_storage_removal_resumes_only_the_same_ledger",
        "packages/openzyme-core/tests/test_offline_removal_fixture.py::test_unknown_storage_absence_is_not_reinterpreted_as_success",
    ),
    "diagnostic-publication-cleanup": (
        "packages/openzyme-core/tests/test_failure_diagnostics.py",
        "packages/openzyme-core/tests/test_agent_git_workspaces.py::test_publication_response_loss_reconciles_same_ref_without_redispatch",
        "packages/openzyme-core/tests/test_agent_git_workspaces.py::test_publication_reconcile_read_failure_preserves_prior_effect_and_new_cause",
        "packages/openzyme-core/tests/test_agent_git_workspaces.py::test_publication_execution_repository_rejects_stale_state_and_fence",
        "packages/openzyme-core/tests/test_bio_research_tools.py::test_workspace_write_orders_primary_then_cleanup_failure",
        "packages/openzyme-core/tests/test_bio_research_tools.py::test_workspace_write_reports_successful_effect_with_cleanup_residue",
    ),
    "scientific-finalization": (
        "packages/openzyme-core/tests/test_scientific_file_deliverables.py",
        "apps/openzyme-host-api/tests/test_aox_file_bundle_finalizer.py",
    ),
    "workspace-job": (
        "apps/mcp-hpc-runner/tests/test_workspace_revision_job_wire.py",
        "apps/openzyme-host-api/tests/test_workspace_revision_execution_boundary.py",
        "packages/openzyme-core/tests/test_workspace_revision_execution_authority.py",
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
    if runner_sources:
        runner_src = str(REPO_ROOT / "apps/mcp-hpc-runner/src")
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            runner_src if not existing else runner_src + os.pathsep + existing
        )
    return environment


def run_closed_non_live_suite(suite_id: str) -> ProductionCompositionReceipt:
    if suite_id == "web-ui":
        command = ("npm", "test")
        cwd = REPO_ROOT / "apps/openzyme-web-ui"
        runner_sources = False
    else:
        selectors = _PYTEST_SELECTIONS.get(suite_id)
        if selectors is None:
            raise ValueError(f"unknown production composition suite {suite_id!r}")
        command = (sys.executable, "-m", "pytest", "-q", *selectors)
        cwd = REPO_ROOT
        runner_sources = suite_id == "workspace-job"
    started = time.monotonic_ns()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=_non_live_environment(runner_sources=runner_sources),
            check=False,
            capture_output=True,
            timeout=45,
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
