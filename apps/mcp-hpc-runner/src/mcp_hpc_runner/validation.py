from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re

from .config import ResourceLimitsConfig
from .models import ExpectedOutput, RunSpec

VALID_EXECUTION_MODES = {"ssh", "sbatch", "auto"}
VALID_SUCCESS_CHECKS = {"exists", "non_empty", "json"}
VALID_STAGE_TARGETS = {"work", "out"}

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_SLURM_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9._+-]{1,255}$")


def _validate_path_text(raw: str, *, field: str) -> None:
    if len(raw) > 1024:
        raise ValueError(f"{field} exceeds the 1024-character path limit")
    if any(ord(char) < 32 or ord(char) == 127 for char in raw) or "\\" in raw:
        raise ValueError(f"{field} contains forbidden control or path characters")


def _validate_path_segments(parts: tuple[str, ...], *, field: str) -> None:
    for part in parts:
        if part in {"", ".", ".."}:
            raise ValueError(f"{field} must not contain empty, '.', or '..' segments")
        if not _SAFE_PATH_SEGMENT.fullmatch(part):
            raise ValueError(
                f"{field} contains a path segment with forbidden characters"
            )


def safe_relative_path(value: str, *, field: str) -> PurePosixPath:
    raw = str(value)
    if not raw:
        raise ValueError(f"{field} must be a non-empty relative path")
    _validate_path_text(raw, field=field)
    if raw.startswith("/"):
        raise ValueError(f"{field} must be a relative path")
    raw_parts = raw.split("/")
    _validate_path_segments(tuple(raw_parts), field=field)
    path = PurePosixPath(raw)
    if path.is_absolute() or path.as_posix() != raw:
        raise ValueError(f"{field} must be a normalized relative path")
    return path


def safe_remote_run_dir(value: str, *, field: str = "remote_run_dir") -> PurePosixPath:
    raw = str(value)
    if not raw:
        raise ValueError(f"{field} must be a non-empty path")
    _validate_path_text(raw, field=field)
    path = PurePosixPath(raw)
    if path.as_posix() != raw:
        raise ValueError(f"{field} must be a normalized path")
    parts = list(path.parts)
    if parts and parts[0] == "/":
        parts.pop(0)
    elif parts and parts[0] == "~":
        parts.pop(0)
    if not parts:
        raise ValueError(f"{field} must identify a per-run directory")
    _validate_path_segments(tuple(parts), field=field)
    return path


def _contained_output_path(root: Path, relative_path: str, *, field: str) -> Path:
    relative = safe_relative_path(relative_path, field=field)
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(*relative.parts)).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"{field} escapes the output root")
    return candidate


def _safe_slurm_token(value: str, *, field: str) -> str | None:
    normalized = str(value)
    if not _SAFE_SLURM_TOKEN.fullmatch(normalized):
        return f"{field} must contain only letters, digits, '.', '_', or '-'"
    return None


def ensure_safe_slurm_token(value: str, *, field: str) -> str:
    error = _safe_slurm_token(value, field=field)
    if error:
        raise ValueError(error)
    return str(value)


def validate_runspec(
    spec: RunSpec,
    *,
    limits: ResourceLimitsConfig | None = None,
    allowed_partitions: tuple[str, ...] | None = None,
) -> list[str]:
    limits = limits or ResourceLimitsConfig()
    errors: list[str] = []
    if not spec.name.strip():
        errors.append("RunSpec.name must be non-empty")
    elif error := _safe_slurm_token(spec.name, field="RunSpec.name"):
        errors.append(error)
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
    elif spec.resources.cpus > limits.max_cpus:
        errors.append(f"resources.cpus must be <= {limits.max_cpus}")
    if spec.resources.mem_mb < 1:
        errors.append("resources.mem_mb must be >= 1")
    elif spec.resources.mem_mb > limits.max_mem_mb:
        errors.append(f"resources.mem_mb must be <= {limits.max_mem_mb}")
    if spec.resources.gpus < 0:
        errors.append("resources.gpus must be >= 0")
    elif spec.resources.gpus > limits.max_gpus:
        errors.append(f"resources.gpus must be <= {limits.max_gpus}")
    if spec.resources.time_minutes < 1:
        errors.append("resources.time_minutes must be >= 1")
    elif spec.resources.time_minutes > limits.max_time_minutes:
        errors.append(f"resources.time_minutes must be <= {limits.max_time_minutes}")
    if spec.resources.partition:
        if error := _safe_slurm_token(
            spec.resources.partition,
            field="resources.partition",
        ):
            errors.append(error)
        elif (
            allowed_partitions is not None
            and spec.resources.partition not in allowed_partitions
        ):
            configured = ", ".join(sorted(allowed_partitions)) or "<none>"
            errors.append(
                "resources.partition must be one of the operator-allowed partitions: "
                + configured
            )

    if spec.run_id is not None and not _SAFE_RUN_ID.fullmatch(str(spec.run_id)):
        errors.append(
            "RunSpec.run_id must contain only letters, digits, '.', '_', or '-' "
            "and must not contain path separators"
        )

    for item in spec.inputs:
        try:
            safe_relative_path(item.remote_path, field="inputs.remote_path")
        except ValueError as exc:
            errors.append(str(exc))
        if item.stage_to not in VALID_STAGE_TARGETS:
            errors.append(
                f"inputs.stage_to must be one of {sorted(VALID_STAGE_TARGETS)}"
            )
        local = Path(item.local_path)
        if item.required and not local.exists():
            errors.append(f"required input is missing: {item.local_path}")
        elif local.exists() and local.is_symlink():
            errors.append(f"input path must not be a symlink: {item.local_path}")

    for output in spec.expected_outputs:
        try:
            safe_relative_path(output.path, field="expected_outputs.path")
        except ValueError as exc:
            errors.append(str(exc))
        if output.kind not in {"file", "dir"}:
            errors.append(f"expected output kind must be file|dir: {output.path}")

    for check in spec.success_checks:
        try:
            safe_relative_path(check.path, field="success_checks.path")
        except ValueError as exc:
            errors.append(str(exc))
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


def ensure_valid_runspec(
    spec: RunSpec,
    *,
    limits: ResourceLimitsConfig | None = None,
    allowed_partitions: tuple[str, ...] | None = None,
) -> None:
    errors = validate_runspec(
        spec,
        limits=limits,
        allowed_partitions=allowed_partitions,
    )
    if errors:
        joined = "\n".join(f"- {error}" for error in errors)
        raise ValueError(f"RunSpec validation failed:\n{joined}")


def validate_expected_outputs(
    local_output_root: Path, expected_outputs: list[ExpectedOutput]
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    empty: list[str] = []
    for expected in expected_outputs:
        candidate = _contained_output_path(
            local_output_root,
            expected.path,
            field="expected_outputs.path",
        )
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
        candidate = _contained_output_path(
            local_output_root,
            check.path,
            field="success_checks.path",
        )
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
