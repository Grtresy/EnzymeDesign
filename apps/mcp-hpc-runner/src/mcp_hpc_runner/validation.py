from __future__ import annotations

from pathlib import Path
import json

from .models import ExpectedOutput, RunSpec

VALID_EXECUTION_MODES = {"ssh", "sbatch", "auto"}
VALID_SUCCESS_CHECKS = {"exists", "non_empty", "json"}


def validate_runspec(spec: RunSpec) -> list[str]:
    errors: list[str] = []
    if not spec.name.strip():
        errors.append("RunSpec.name must be non-empty")
    if not spec.stage.strip():
        errors.append("RunSpec.stage must be non-empty")
    if not spec.command:
        errors.append("RunSpec.command must contain at least one argv token")
    if spec.execution_mode not in VALID_EXECUTION_MODES:
        errors.append(
            f"RunSpec.execution_mode must be one of {sorted(VALID_EXECUTION_MODES)}"
        )

    if spec.resources.cpus < 1:
        errors.append("resources.cpus must be >= 1")
    if spec.resources.mem_mb < 1:
        errors.append("resources.mem_mb must be >= 1")
    if spec.resources.gpus < 0:
        errors.append("resources.gpus must be >= 0")
    if spec.resources.time_minutes < 1:
        errors.append("resources.time_minutes must be >= 1")

    for item in spec.inputs:
        if not item.remote_path or item.remote_path.startswith("/"):
            errors.append(
                "inputs.remote_path must be relative to remote work/ directory"
            )
        local = Path(item.local_path)
        if item.required and not local.exists():
            errors.append(f"required input is missing: {item.local_path}")

    for output in spec.expected_outputs:
        if output.path.startswith("/"):
            errors.append("expected_outputs.path must be relative under out/")
        if output.kind not in {"file", "dir"}:
            errors.append(f"expected output kind must be file|dir: {output.path}")

    for check in spec.success_checks:
        if check.check_type not in VALID_SUCCESS_CHECKS:
            errors.append(
                f"unsupported success check type '{check.check_type}' for {check.path}"
            )

    for signature in spec.failure_signatures:
        if not signature.pattern:
            errors.append("failure signature pattern must be non-empty")
        if not signature.error_code:
            errors.append("failure signature error_code must be non-empty")

    return errors


def ensure_valid_runspec(spec: RunSpec) -> None:
    errors = validate_runspec(spec)
    if errors:
        joined = "\n".join(f"- {error}" for error in errors)
        raise ValueError(f"RunSpec validation failed:\n{joined}")


def validate_expected_outputs(
    local_output_root: Path, expected_outputs: list[ExpectedOutput]
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    empty: list[str] = []
    for expected in expected_outputs:
        candidate = local_output_root / expected.path
        if not candidate.exists():
            if expected.required:
                missing.append(expected.path)
            continue
        if expected.non_empty:
            if expected.kind == "dir":
                if not any(candidate.iterdir()):
                    empty.append(expected.path)
            elif candidate.is_file() and candidate.stat().st_size == 0:
                empty.append(expected.path)
    return missing, empty


def run_success_checks(local_output_root: Path, spec: RunSpec) -> list[str]:
    failures: list[str] = []
    for check in spec.success_checks:
        candidate = local_output_root / check.path
        if check.check_type == "exists" and not candidate.exists():
            failures.append(f"missing required path: {check.path}")
        elif check.check_type == "non_empty":
            if not candidate.exists():
                failures.append(f"missing required path: {check.path}")
            elif candidate.is_file() and candidate.stat().st_size == 0:
                failures.append(f"path is empty: {check.path}")
            elif candidate.is_dir() and not any(candidate.iterdir()):
                failures.append(f"directory is empty: {check.path}")
        elif check.check_type == "json":
            if not candidate.exists():
                failures.append(f"missing required json file: {check.path}")
                continue
            try:
                json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                failures.append(f"invalid json output: {check.path}")
    return failures
