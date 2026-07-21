from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from .config import RunnerConfig
from .models import RunSpec
from .recovery import classify_pre_effect_failure
from .recovery import PreEffectFailureClass
from .remote import CommandRunner
from .transport import SshCommandCompiler
from .transport import SshTransportManager
from .verification import AuthorizedInput
from .verification import RemoteInputVerifier
from .verification import RemoteVerificationStatus


# ── check descriptor schema ───────────────────────────────────────────────────
# Each entry: {"kind": str, "path": str, "severity": "error"|"warn"}
# Supported kinds: "binary", "sif", "dir", "file"
# ─────────────────────────────────────────────────────────────────────────────

_REMOTE_CHECK_SCRIPT = """\
import json, os, sys

checks = {checks_json}
descriptor_set_digest = {descriptor_set_digest_json}
results = []
for check in checks:
    kind = check["kind"]
    declared_path = check["path"]
    path = os.path.expanduser(declared_path)
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
    r = {{
        "check_id": check["check_id"],
        "kind": kind,
        "declared_path": declared_path,
        "path": path,
        "status": status,
    }}
    if reason:
        r["reason"] = reason
    results.append(r)
print(json.dumps({{
    "schema_version": "remote_preflight_receipt@1",
    "descriptor_set_digest": descriptor_set_digest,
    "checks": results,
}}))
"""


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _bind_check_descriptors(
    descriptors: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    bound: list[dict[str, Any]] = []
    for ordinal, descriptor in enumerate(descriptors, start=1):
        identity = {
            "schema_version": "preflight_check_descriptor@1",
            "ordinal": ordinal,
            "kind": descriptor["kind"],
            "path": descriptor["path"],
            "severity": descriptor["severity"],
        }
        bound.append({**descriptor, "check_id": _canonical_digest(identity)})
    return bound, _canonical_digest(
        {
            "schema_version": "preflight_descriptor_set@1",
            "descriptors": bound,
        }
    )


class PreflightFailureClass(StrEnum):
    NONE = "none"
    DETERMINISTIC_VALIDATION = "deterministic_validation"
    AUTHENTICATED_TRANSPORT = "authenticated_transport"


@dataclass(slots=True)
class PreflightResult:
    checks: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = True
    failure_class: PreflightFailureClass = PreflightFailureClass.NONE
    timestamp: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "passed": self.passed,
            "failure_class": self.failure_class.value,
            "checks": self.checks,
        }


class PreflightError(RuntimeError):
    def __init__(self, manifest: dict[str, Any]) -> None:
        failed = [c for c in manifest.get("checks", []) if c["status"] == "error"]
        reasons = "; ".join(c.get("reason", c["path"]) for c in failed)
        super().__init__(f"Preflight checks failed: {reasons}")
        self.manifest = manifest


class PreflightChecker:
    def __init__(
        self,
        config: RunnerConfig,
        command_runner: CommandRunner,
        ssh_compiler: SshCommandCompiler | None = None,
        transport_manager: SshTransportManager | None = None,
    ) -> None:
        self.config = config
        self.command_runner = command_runner
        self.ssh_compiler = ssh_compiler or SshCommandCompiler.legacy(
            config.cluster.ssh_target
        )
        self.transport_manager = transport_manager or SshTransportManager(
            config,
            command_runner,
        )
        self.remote_verifier = RemoteInputVerifier(self.transport_manager)

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

    def run_checks(
        self,
        spec: RunSpec,
        remote_run_dir: str,
        *,
        verified_inputs: list[dict[str, Any]] | None = None,
    ) -> PreflightResult:
        digest_checks, digest_failure_class = self._reverify_inputs(
            verified_inputs or []
        )
        if digest_failure_class is not PreflightFailureClass.NONE:
            return PreflightResult(
                checks=digest_checks,
                passed=False,
                failure_class=digest_failure_class,
            )
        descriptors = self._build_check_descriptors(spec, remote_run_dir)
        if not descriptors:
            return PreflightResult(checks=digest_checks, passed=True)

        bound_descriptors, descriptor_set_digest = _bind_check_descriptors(
            descriptors
        )

        script = _REMOTE_CHECK_SCRIPT.format(
            checks_json=json.dumps(bound_descriptors),
            descriptor_set_digest_json=json.dumps(descriptor_set_digest),
        )
        raw = self.transport_manager.run_ssh(
            ["python3", "-c", script],
            check=False,
            timeout=self.config.execution.preflight_timeout_seconds,
            stage="preflight",
        )

        if raw.returncode != 0:
            failure_class = classify_pre_effect_failure(raw)
            checks = [{
                "kind": "preflight_script",
                "path": "",
                "status": "error",
                "reason": (
                    "authenticated_transport_unavailable"
                    if failure_class is PreEffectFailureClass.AUTHENTICATED_TRANSPORT
                    else "preflight_script_failed"
                ),
            }]
            return PreflightResult(
                checks=[*digest_checks, *checks],
                passed=False,
                failure_class=(
                    PreflightFailureClass.AUTHENTICATED_TRANSPORT
                    if failure_class is PreEffectFailureClass.AUTHENTICATED_TRANSPORT
                    else PreflightFailureClass.DETERMINISTIC_VALIDATION
                ),
            )

        try:
            decoded = json.loads(raw.stdout.strip())
            if (
                not isinstance(decoded, dict)
                or set(decoded) != {
                    "schema_version",
                    "descriptor_set_digest",
                    "checks",
                }
                or decoded.get("schema_version") != "remote_preflight_receipt@1"
                or decoded.get("descriptor_set_digest") != descriptor_set_digest
                or not isinstance(decoded.get("checks"), list)
                or len(decoded["checks"]) != len(bound_descriptors)
            ):
                raise ValueError("preflight receipt binding is invalid")
            checks = []
            for item, expected in zip(
                decoded["checks"],
                bound_descriptors,
                strict=True,
            ):
                if (
                    not isinstance(item, dict)
                    or not {
                        "check_id",
                        "kind",
                        "declared_path",
                        "path",
                        "status",
                    }.issubset(item)
                    or not set(item).issubset(
                        {
                            "check_id",
                            "kind",
                            "declared_path",
                            "path",
                            "status",
                            "reason",
                        }
                    )
                    or item.get("check_id") != expected["check_id"]
                    or item.get("kind") != expected["kind"]
                    or item.get("declared_path") != expected["path"]
                    or not isinstance(item.get("kind"), str)
                    or not isinstance(item.get("path"), str)
                    or item.get("status") not in {"pass", "warn", "error"}
                    or (
                        item.get("status") != "pass"
                        and item.get("status") != expected["severity"]
                    )
                    or (
                        item.get("reason") is not None
                        and not isinstance(item.get("reason"), str)
                    )
                ):
                    raise ValueError("preflight receipt entry is invalid")
                checks.append(dict(item))
        except (json.JSONDecodeError, ValueError):
            checks = [{
                "kind": "preflight_script",
                "path": "",
                "status": "error",
                "reason": "preflight_receipt_invalid",
            }]
            return PreflightResult(
                checks=[*digest_checks, *checks],
                passed=False,
                failure_class=PreflightFailureClass.DETERMINISTIC_VALIDATION,
            )

        passed = all(c["status"] != "error" for c in checks)
        return PreflightResult(
            checks=[*digest_checks, *checks],
            passed=passed,
            failure_class=(
                PreflightFailureClass.NONE
                if passed
                else PreflightFailureClass.DETERMINISTIC_VALIDATION
            ),
        )

    def _reverify_inputs(
        self,
        verified_inputs: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], PreflightFailureClass]:
        checks: list[dict[str, Any]] = []
        failure_class = PreflightFailureClass.NONE
        for raw in verified_inputs:
            ordinal = int(raw["input_ordinal"])
            authorized = AuthorizedInput.from_path(Path(str(raw["local_path"])))
            if (
                authorized.content_digest != raw.get("content_digest")
                or authorized.contract_digest != raw.get("authorized_input_digest")
            ):
                checks.append(
                    {
                        "kind": "input_digest",
                        "path": "",
                        "input_ordinal": ordinal,
                        "status": "error",
                        "reason": "authorized_input_changed_after_staging",
                    }
                )
                failure_class = PreflightFailureClass.DETERMINISTIC_VALIDATION
                continue
            verification = self.remote_verifier.verify(
                str(raw["remote_path"]),
                authorized,
                timeout=self.config.execution.preflight_timeout_seconds,
            )
            checks.append(
                {
                    "kind": "input_digest",
                    "path": "",
                    "input_ordinal": ordinal,
                    "status": "pass" if verification.verified else "error",
                    "reason": verification.status.value,
                    "content_digest": authorized.content_digest,
                    "verification_receipt_digest": verification.receipt_digest,
                }
            )
            if verification.verified:
                continue
            if verification.status is RemoteVerificationStatus.TRANSPORT_ERROR:
                failure_class = PreflightFailureClass.AUTHENTICATED_TRANSPORT
            elif failure_class is PreflightFailureClass.NONE:
                failure_class = PreflightFailureClass.DETERMINISTIC_VALIDATION
        return checks, failure_class


def run_preflight(
    spec: RunSpec,
    remote_run_dir: str,
    config: RunnerConfig,
    command_runner: CommandRunner | SshTransportManager,
    *,
    verified_inputs: list[dict[str, Any]] | None = None,
) -> PreflightResult:
    if isinstance(command_runner, SshTransportManager):
        transport_manager = command_runner
        raw_command_runner = command_runner.command_runner
    else:
        transport_manager = None
        raw_command_runner = command_runner
    checker = PreflightChecker(
        config,
        raw_command_runner,  # type: ignore[arg-type]
        None,
        transport_manager,
    )
    return checker.run_checks(
        spec,
        remote_run_dir,
        verified_inputs=verified_inputs,
    )


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
    runner_attempt_link: dict[str, object] | None = None,
) -> dict[str, Any]:
    manifest = {
        "run_id": run_id,
        "adapter_id": adapter_id,
        **result.to_dict(),
    }
    if sbatch_args:
        manifest["sbatch_args"] = sbatch_args
    if runner_attempt_link:
        manifest["runner_attempt"] = dict(runner_attempt_link)
    return manifest
