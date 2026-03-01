from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .models import FallbackReason


_SHELL_SNIPPETS = ("&&", "||", ";", "`", "$(")


def ensure_argv_only(argv: list[str]) -> list[str]:
    if not argv:
        raise ValueError("RunSpec.command must contain at least one argv token")
    cleaned: list[str] = []
    for token in argv:
        value = str(token)
        if not value:
            raise ValueError("RunSpec.command tokens must be non-empty")
        if any(snippet in value for snippet in _SHELL_SNIPPETS):
            raise ValueError(
                "RunSpec.command must use argv tokens only (shell snippets are disallowed)"
            )
        cleaned.append(value)
    return cleaned


def ensure_relative_path(path: str, *, field_name: str) -> str:
    normalized = PurePosixPath(str(path))
    if normalized.is_absolute():
        raise ValueError(f"{field_name} must be a relative path")
    if ".." in normalized.parts:
        raise ValueError(f"{field_name} must not escape working directories")
    return str(normalized)


def staged_input(
    local_path: str, remote_path: str, *, stage_to: str = "work"
) -> dict[str, Any]:
    if stage_to not in ("work", "out"):
        raise ValueError(f"staged_input stage_to must be 'work' or 'out', got {stage_to!r}")
    return {
        "local_path": str(local_path),
        "remote_path": ensure_relative_path(
            remote_path, field_name="inputs.remote_path"
        ),
        "required": True,
        "stage_to": stage_to,
    }


def expected_output(
    path: str,
    *,
    kind: str,
    required: bool = True,
    non_empty: bool = False,
) -> dict[str, Any]:
    return {
        "path": ensure_relative_path(path, field_name="expected_outputs.path"),
        "kind": kind,
        "required": required,
        "non_empty": non_empty,
    }


def success_check(check_type: str, path: str) -> dict[str, str]:
    return {
        "check_type": check_type,
        "path": ensure_relative_path(path, field_name="success_checks.path"),
    }


def failure_signature(pattern: str, error_code: str) -> dict[str, str]:
    return {"pattern": pattern, "error_code": error_code}


def build_metadata(
    *,
    adapter_id: str,
    selected_mode: str,
    fallback: list[FallbackReason],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tool_contract": {
            "adapter_id": adapter_id,
            "selected_mode": selected_mode,
            "fallback": [step.to_dict() for step in fallback],
            **(extra or {}),
        }
    }


def build_runspec(
    *,
    name: str,
    stage: str,
    command: list[str],
    resources: dict[str, Any],
    inputs: list[dict[str, Any]],
    expected_outputs: list[dict[str, Any]],
    success_checks: list[dict[str, Any]],
    failure_signatures: list[dict[str, str]],
    fallback: list[FallbackReason],
    metadata: dict[str, Any],
    execution_mode: str = "auto",
) -> dict[str, Any]:
    return {
        "name": name,
        "stage": stage,
        "command": ensure_argv_only(command),
        "execution_mode": execution_mode,
        "resources": resources,
        "inputs": inputs,
        "expected_outputs": expected_outputs,
        "success_checks": success_checks,
        "failure_signatures": failure_signatures,
        "fallback": [step.to_dict() for step in fallback],
        "metadata": metadata,
    }
