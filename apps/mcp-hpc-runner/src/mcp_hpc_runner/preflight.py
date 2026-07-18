from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from .config import RunnerConfig
from .models import RunSpec
from .remote import CommandRunner, wrap_ssh


# ── check descriptor schema ───────────────────────────────────────────────────
# Each entry: {"kind": str, "path": str, "severity": "error"|"warn"}
# Supported kinds: "binary", "sif", "dir", "file"
# ─────────────────────────────────────────────────────────────────────────────

_REMOTE_CHECK_SCRIPT = """\
import json, os, sys

checks = {checks_json}
results = []
for check in checks:
    kind = check["kind"]
    path = os.path.expanduser(check["path"])
    severity = check.get("severity", "error")
    status = "pass"
    reason = None
    if kind == "binary":
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            status = severity
            reason = f"binary not executable: {{path}}"
    elif kind == "sif":
        if not os.path.isfile(path) or not os.access(path, os.R_OK):
            status = severity
            reason = f"SIF image not found or unreadable: {{path}}"
    elif kind == "dir":
        if not os.path.isdir(path):
            status = severity
            reason = f"directory not found: {{path}}"
    elif kind == "file":
        if not os.path.isfile(path):
            status = severity
            reason = f"file not found: {{path}}"
    else:
        status = "warn"
        reason = f"unknown check kind: {{kind}}"
    r = {{"kind": kind, "path": path, "status": status}}
    if reason:
        r["reason"] = reason
    results.append(r)
print(json.dumps(results))
"""


@dataclass(slots=True)
class PreflightResult:
    checks: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "passed": self.passed,
            "checks": self.checks,
        }


class PreflightError(RuntimeError):
    def __init__(self, manifest: dict[str, Any]) -> None:
        failed = [c for c in manifest.get("checks", []) if c["status"] == "error"]
        reasons = "; ".join(c.get("reason", c["path"]) for c in failed)
        super().__init__(f"Preflight checks failed: {reasons}")
        self.manifest = manifest


class PreflightChecker:
    def __init__(self, config: RunnerConfig, command_runner: CommandRunner) -> None:
        self.config = config
        self.command_runner = command_runner

    def _ssh_target(self) -> str:
        return self.config.cluster.ssh_target

    def _build_check_descriptors(
        self, spec: RunSpec, remote_run_dir: str
    ) -> list[dict[str, Any]]:
        descriptors: list[dict[str, Any]] = []

        if spec.metadata.get("toolchain_runtime_request"):
            descriptors.append(
                {
                    "kind": "binary",
                    "path": self.config.execution.apptainer_executable,
                    "severity": "error",
                }
            )

        # 1. Tool entrypoint (binary or SIF image) from preflight_hints in metadata.
        hints = (
            spec.metadata
            .get("tool_contract", {})
            .get("preflight_hints", {})
        )
        entrypoint = hints.get("entrypoint")
        if entrypoint and entrypoint.get("path"):
            descriptors.append({
                "kind": entrypoint["kind"],   # "binary" | "sif"
                "path": entrypoint["path"],
                "severity": "error",
            })

        # 2. Extra bind paths (databases, model dirs).
        for bind_path in hints.get("bind_paths", []):
            descriptors.append({
                "kind": "dir",
                "path": bind_path,
                "severity": "warn",  # missing db is a warning, not always fatal
            })

        # 3. Staged input files.
        for inp in spec.inputs:
            full_path = str(
                PurePosixPath(remote_run_dir) / inp.stage_to / inp.remote_path
            )
            descriptors.append({
                "kind": "file",
                "path": full_path,
                "severity": "error",
            })

        # 4. Output directory writable.
        out_dir = str(PurePosixPath(remote_run_dir) / "out")
        descriptors.append({
            "kind": "dir",
            "path": out_dir,
            "severity": "error",
        })

        return descriptors

    def run_checks(self, spec: RunSpec, remote_run_dir: str) -> PreflightResult:
        descriptors = self._build_check_descriptors(spec, remote_run_dir)
        if not descriptors:
            return PreflightResult(checks=[], passed=True)

        script = _REMOTE_CHECK_SCRIPT.format(
            checks_json=json.dumps(descriptors)
        )
        ssh_cmd = wrap_ssh(
            self._ssh_target(),
            ["python3", "-c", script],
        )
        raw = self.command_runner.run(
            ssh_cmd,
            check=False,
            timeout=self.config.execution.preflight_timeout_seconds,
            stage="preflight",
        )

        if raw.returncode != 0:
            # Could not even run the preflight script — treat as a single error.
            checks = [{
                "kind": "preflight_script",
                "path": "",
                "status": "error",
                "reason": f"preflight script failed to run: {raw.stderr.strip()}",
            }]
            return PreflightResult(checks=checks, passed=False)

        try:
            checks: list[dict[str, Any]] = json.loads(raw.stdout.strip())
        except json.JSONDecodeError:
            checks = [{
                "kind": "preflight_script",
                "path": "",
                "status": "error",
                "reason": f"preflight script returned non-JSON: {raw.stdout[:200]}",
            }]
            return PreflightResult(checks=checks, passed=False)

        passed = all(c["status"] != "error" for c in checks)
        return PreflightResult(checks=checks, passed=passed)


def run_preflight(
    spec: RunSpec,
    remote_run_dir: str,
    config: RunnerConfig,
    command_runner: CommandRunner,
) -> PreflightResult:
    checker = PreflightChecker(config, command_runner)
    return checker.run_checks(spec, remote_run_dir)


def format_preflight_summary(result: PreflightResult) -> str:
    lines = [f"preflight: {'PASS' if result.passed else 'FAIL'}"]
    for check in result.checks:
        icon = {"pass": "✓", "warn": "⚠", "error": "✗"}.get(check["status"], "?")
        path = check.get("path", "")
        reason = check.get("reason", "")
        detail = f" — {reason}" if reason else ""
        lines.append(f"  {icon} [{check['kind']}] {path}{detail}")
    return "\n".join(lines)


def preflight_manifest(
    run_id: str,
    adapter_id: str,
    result: PreflightResult,
    sbatch_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = {
        "run_id": run_id,
        "adapter_id": adapter_id,
        **result.to_dict(),
    }
    if sbatch_args:
        manifest["sbatch_args"] = sbatch_args
    return manifest
