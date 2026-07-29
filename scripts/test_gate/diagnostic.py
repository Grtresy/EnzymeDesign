"""Closed, explicitly non-authoritative diagnostic selection and execution."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
from types import MappingProxyType
import time
from typing import Any, Callable, Mapping, Sequence

from .config import TestGateConfig
from .diagnostic_guard import DIAGNOSTIC_GUARD_ENV
from .model import (
    EXECUTION_PLAN_SCHEMA_ID,
    PYTEST_OBSERVATION_SCHEMA_ID,
    RECEIPT_SCHEMA_ID,
    STAGE_RESULT_SCHEMA_ID,
    canonical_document_bytes,
    canonical_json_bytes,
    load_canonical_document_bytes,
    seal_document,
    sha256_digest,
    verify_sealed_document,
)
from .runner import (
    ProcessResult,
    create_new_output_root,
    publish_no_replace,
    run_command,
)
from .shadow import (
    FORBIDDEN_NON_LIVE_MARKERS,
    CollectionSnapshot,
    assert_source_stable,
    closed_non_live_environment,
    load_pytest_observation,
)
from .source import SourceIdentity, collect_source_identity

DIAGNOSTIC_PLANNER_ID = "openzyme_test_diagnostic_planner@1"
NON_LIVE_MARKER_EXPRESSION = (
    "not integration and not live_llm and not live_tavily and not live_hpc "
    "and not live_e2e and not seeded_live_smoke and not quality_eval"
)
_PYTHON_SUFFIXES = frozenset({".py", ".pyi"})


class DiagnosticError(RuntimeError):
    """Raised when diagnostic selection or evidence does not close."""


@dataclass(frozen=True)
class ContractGroup:
    id: str
    lint_paths: tuple[str, ...]
    pytest_selectors: tuple[str, ...]


CONTRACT_GROUPS: Mapping[str, ContractGroup] = MappingProxyType(
    {
        "compatibility_audit": ContractGroup(
            id="compatibility_audit",
            lint_paths=("scripts/audit-v3-compat-callers.py",),
            pytest_selectors=(
                "packages/openzyme-core/tests/test_compat_caller_audit.py",
            ),
        ),
        "test_gate": ContractGroup(
            id="test_gate",
            lint_paths=(
                "scripts/run-test-gate.py",
                "scripts/test_gate",
            ),
            pytest_selectors=(
                "packages/openzyme-core/tests/test_test_gate_affected.py",
                "packages/openzyme-core/tests/test_test_gate_authoritative.py",
                "packages/openzyme-core/tests/test_test_gate_benchmark.py",
                "packages/openzyme-core/tests/test_test_gate_config.py",
                "packages/openzyme-core/tests/test_test_gate_contract.py",
                "packages/openzyme-core/tests/test_test_gate_diagnostic.py",
                "packages/openzyme-core/tests/test_test_gate_model.py",
                "packages/openzyme-core/tests/test_test_gate_pytest_plugin.py",
                "packages/openzyme-core/tests/test_test_gate_replay.py",
                "packages/openzyme-core/tests/test_test_gate_resource.py",
                "packages/openzyme-core/tests/test_test_gate_runner.py",
                "packages/openzyme-core/tests/test_test_gate_shadow.py",
                "packages/openzyme-core/tests/test_test_gate_source.py",
            ),
        ),
        "v3_runtime_protocol": ContractGroup(
            id="v3_runtime_protocol",
            lint_paths=("packages/openzyme-core",),
            pytest_selectors=(
                "packages/openzyme-core/tests/test_agent_scheduler.py",
                "packages/openzyme-core/tests/test_protocols.py",
            ),
        ),
    }
)


@dataclass(frozen=True)
class FocusedSelection:
    input_lint_paths: tuple[str, ...]
    input_pytest_paths: tuple[str, ...]
    input_node_ids: tuple[str, ...]
    input_contract_groups: tuple[str, ...]
    lint_paths: tuple[str, ...]
    pytest_selectors: tuple[str, ...]
    collection_selectors: tuple[str, ...]
    matched_contract_groups: tuple[str, ...]

    def as_plan_dict(self) -> dict[str, object]:
        return {
            "input": {
                "lint_paths": list(self.input_lint_paths),
                "pytest_paths": list(self.input_pytest_paths),
                "node_ids": list(self.input_node_ids),
                "contract_groups": list(self.input_contract_groups),
                "changed_paths": [],
                "base_ref": None,
            },
            "expanded": {
                "lint_paths": list(self.lint_paths),
                "pytest_selectors": list(self.pytest_selectors),
                "collection_selectors": list(self.collection_selectors),
            },
            "matched_rules": list(self.matched_contract_groups),
            "unknown_paths": [],
            "collection_deselection_policy": "reject_any",
            "policy_deselected_nodes": [],
            "frontend": {
                "included": False,
                "stage_ids": [],
                "frontend_omission": "diagnostic_only",
                "reason": (
                    "focused selection does not infer affected frontend closure"
                ),
            },
        }


@dataclass(frozen=True)
class DiagnosticRunResult:
    output_root: Path
    plan: Mapping[str, Any]
    receipt: Mapping[str, Any]
    terminal_status: str


@dataclass(frozen=True)
class _Observation:
    snapshot: CollectionSnapshot
    document: Mapping[str, Any]
    document_digest: str


def _normalize_relative_path(
    repo_root: Path,
    value: str,
    *,
    context: str,
) -> tuple[str, Path]:
    if not isinstance(value, str) or not value:
        raise DiagnosticError(f"{context} must be a nonempty string")
    if "\\" in value:
        raise DiagnosticError(f"{context} must use repository POSIX separators")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise DiagnosticError(f"{context} must be repository-relative: {value!r}")
    normalized = pure.as_posix()
    if normalized != value:
        raise DiagnosticError(
            f"{context} must use its canonical repository-relative form: "
            f"{value!r} != {normalized!r}"
        )
    candidate = repo_root / normalized
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise DiagnosticError(f"{context} does not exist: {value!r}") from exc
    try:
        inside = os.path.commonpath((str(repo_root), str(resolved))) == str(
            repo_root
        )
    except ValueError as exc:
        raise DiagnosticError(f"cannot validate {context}: {value!r}") from exc
    if not inside:
        raise DiagnosticError(f"{context} escapes the repository: {value!r}")
    if candidate.is_symlink():
        raise DiagnosticError(f"{context} must not be a symlink: {value!r}")
    if not resolved.is_file() and not resolved.is_dir():
        raise DiagnosticError(
            f"{context} is not a regular file or directory: {value!r}"
        )
    return normalized, resolved


def _directory_contains_python(path: Path) -> bool:
    for directory, directory_names, file_names in os.walk(path):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name
            not in {
                ".git",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                ".venv",
                "__pycache__",
                "node_modules",
            }
        )
        directory_path = Path(directory)
        if any(
            (directory_path / name).suffix.lower() in _PYTHON_SUFFIXES
            for name in file_names
        ):
            return True
    return False


def _validate_lint_path(repo_root: Path, value: str) -> str:
    normalized, resolved = _normalize_relative_path(
        repo_root,
        value,
        context="lint path",
    )
    if resolved.is_file() and resolved.suffix.lower() not in _PYTHON_SUFFIXES:
        raise DiagnosticError(
            f"lint path must be a Python file or Python-containing directory: {value!r}"
        )
    if resolved.is_dir() and not _directory_contains_python(resolved):
        raise DiagnosticError(f"lint directory contains no Python source: {value!r}")
    return normalized


def _validate_pytest_path(repo_root: Path, value: str) -> str:
    if "::" in value:
        raise DiagnosticError(
            "pytest path must not contain a node suffix; use --node-id instead"
        )
    normalized, resolved = _normalize_relative_path(
        repo_root,
        value,
        context="pytest path",
    )
    if resolved.is_file() and resolved.suffix.lower() != ".py":
        raise DiagnosticError(
            f"pytest path must be a Python test file or directory: {value!r}"
        )
    return normalized


def _validate_node_id(repo_root: Path, value: str) -> str:
    path_part, separator, node_part = value.partition("::")
    if not separator or not path_part or not node_part:
        raise DiagnosticError(
            f"exact node id must contain a path and :: suffix: {value!r}"
        )
    if any(not component for component in node_part.split("::")):
        raise DiagnosticError(f"exact node id has an empty component: {value!r}")
    normalized, resolved = _normalize_relative_path(
        repo_root,
        path_part,
        context="exact node path",
    )
    if not resolved.is_file() or resolved.suffix.lower() != ".py":
        raise DiagnosticError(f"exact node path must be a Python file: {value!r}")
    return f"{normalized}::{node_part}"


def _selector_covers_node(selector: str, node_id: str) -> bool:
    node_path = PurePosixPath(node_id.partition("::")[0])
    selector_path = PurePosixPath(selector)
    if selector_path.suffix:
        return selector_path == node_path
    return selector_path == node_path or selector_path in node_path.parents


def expand_focused_selection(
    repo_root: Path,
    *,
    lint_paths: Sequence[str] = (),
    pytest_paths: Sequence[str] = (),
    node_ids: Sequence[str] = (),
    contract_groups: Sequence[str] = (),
) -> FocusedSelection:
    """Validate and deterministically close one caller-selected focused request."""

    try:
        root = repo_root.resolve(strict=True)
    except OSError as exc:
        raise DiagnosticError(f"repository root does not exist: {repo_root}") from exc
    if not root.is_dir():
        raise DiagnosticError(f"repository root is not a directory: {root}")
    raw_inputs = tuple(lint_paths) + tuple(pytest_paths) + tuple(node_ids) + tuple(
        contract_groups
    )
    if not raw_inputs:
        raise DiagnosticError(
            "focused diagnostic requires at least one lint path, pytest path, "
            "exact node id, or contract group"
        )

    normalized_groups = tuple(sorted(set(contract_groups)))
    unknown_groups = sorted(set(normalized_groups) - set(CONTRACT_GROUPS))
    if unknown_groups:
        raise DiagnosticError(
            "unknown diagnostic contract group(s): " + ", ".join(unknown_groups)
        )
    group_lint = tuple(
        path
        for group_id in normalized_groups
        for path in CONTRACT_GROUPS[group_id].lint_paths
    )
    group_pytest = tuple(
        selector
        for group_id in normalized_groups
        for selector in CONTRACT_GROUPS[group_id].pytest_selectors
    )
    normalized_lint = tuple(
        sorted(
            {
                _validate_lint_path(root, value)
                for value in (*lint_paths, *group_lint)
            }
        )
    )
    normalized_pytest_paths = tuple(
        sorted(
            {
                _validate_pytest_path(root, value)
                for value in (*pytest_paths, *group_pytest)
            }
        )
    )
    normalized_node_ids = tuple(
        sorted({_validate_node_id(root, value) for value in node_ids})
    )
    pytest_selectors = tuple(
        sorted({*normalized_pytest_paths, *normalized_node_ids})
    )
    collection_selectors = list(normalized_pytest_paths)
    for node_id in normalized_node_ids:
        if not any(
            _selector_covers_node(selector, node_id)
            for selector in normalized_pytest_paths
        ):
            collection_selectors.append(node_id)
    if not normalized_lint and not pytest_selectors:
        raise DiagnosticError("focused diagnostic expanded to zero checks")
    return FocusedSelection(
        input_lint_paths=tuple(lint_paths),
        input_pytest_paths=tuple(pytest_paths),
        input_node_ids=tuple(node_ids),
        input_contract_groups=tuple(contract_groups),
        lint_paths=normalized_lint,
        pytest_selectors=pytest_selectors,
        collection_selectors=tuple(sorted(set(collection_selectors))),
        matched_contract_groups=normalized_groups,
    )


def diagnostic_environment(
    repo_root: Path,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Create the closed diagnostic process environment."""

    environment = closed_non_live_environment(source, qualification=False)
    environment["PYTHONPATH"] = str(repo_root / "scripts")
    environment[DIAGNOSTIC_GUARD_ENV] = "1"
    return environment


def _observation_arguments(
    *,
    output_path: Path,
    invocation_id: str,
    role: str,
    mode: str,
) -> tuple[str, ...]:
    return (
        "-p",
        "test_gate.pytest_plugin",
        "-p",
        "test_gate.diagnostic_guard",
        "--test-gate-diagnostic-guard",
        "--test-gate-observation",
        str(output_path),
        "--test-gate-invocation-id",
        invocation_id,
        "--test-gate-role",
        role,
        "--test-gate-observation-mode",
        mode,
    )


def _pytest_prefix() -> tuple[str, ...]:
    return (
        "uv",
        "run",
        "pytest",
        "--rootdir=.",
        "-q",
        "-o",
        "addopts=",
        "--import-mode=importlib",
    )


def _load_observation(
    path: Path,
    *,
    invocation_id: str,
    role: str,
    mode: str,
) -> _Observation:
    snapshot = load_pytest_observation(
        path,
        expected_invocation_id=invocation_id,
        expected_role=role,
        expected_mode=mode,
    )
    try:
        content = path.read_bytes()
        document = load_canonical_document_bytes(content)
    except (OSError, ValueError) as exc:
        raise DiagnosticError(f"cannot load diagnostic observation {path}: {exc}") from exc
    if document["schema_id"] != PYTEST_OBSERVATION_SCHEMA_ID:
        raise DiagnosticError("diagnostic observation schema drifted")
    return _Observation(
        snapshot=snapshot,
        document=document,
        document_digest=sha256_digest(content),
    )


def _forbidden_nodes(snapshot: CollectionSnapshot) -> tuple[dict[str, object], ...]:
    forbidden: list[dict[str, object]] = []
    for node_id, markers in snapshot.markers:
        blocked = sorted(set(markers) & FORBIDDEN_NON_LIVE_MARKERS)
        if blocked:
            forbidden.append({"node_id": node_id, "markers": blocked})
    return tuple(forbidden)


def _classified_policy_deselections(
    observation: _Observation,
) -> tuple[dict[str, object], ...]:
    raw_deselected = tuple(observation.document["deselected"])
    if not raw_deselected:
        return ()
    if "deselected_markers" not in observation.document:
        raise DiagnosticError(
            "affected collection omitted marker evidence for policy deselection"
        )
    classified: list[dict[str, object]] = []
    for node_id, markers in observation.snapshot.deselected_markers:
        blocked = sorted(set(markers) & FORBIDDEN_NON_LIVE_MARKERS)
        if not blocked:
            raise DiagnosticError(
                "affected collection unexpectedly deselected a non-live node: "
                f"{node_id}"
            )
        classified.append({"node_id": node_id, "markers": blocked})
    return tuple(classified)


def _assert_source_unchanged(
    before: SourceIdentity,
    repo_root: Path,
    *,
    collector: Callable[[Path], SourceIdentity],
) -> None:
    assert_source_stable(before, collector(repo_root))


def _stage_document(
    *,
    invocation_id: str,
    plan_digest: str,
    stage_id: str,
    environment_digest: str,
    result: ProcessResult,
) -> dict[str, Any]:
    return seal_document(
        STAGE_RESULT_SCHEMA_ID,
        {
            "invocation_id": invocation_id,
            "plan_digest": plan_digest,
            "stage_id": stage_id,
            "argv": list(result.argv),
            "cwd": result.cwd,
            "environment_digest": environment_digest,
            "outcome": result.outcome,
            "started_monotonic_ns": result.started_monotonic_ns,
            "duration_ns": result.duration_ns,
            "exit_code": result.exit_code,
            "stdout_digest": result.stdout.digest,
            "stdout_tail": result.stdout.tail,
            "stderr_digest": result.stderr.digest,
            "stderr_tail": result.stderr.tail,
            "timed_out": result.timed_out,
            "retirement": {
                "term_sent": result.term_sent,
                "kill_sent": result.kill_sent,
                "error": result.error,
            },
        },
    )


def _publish_stage(
    *,
    evidence_root: Path,
    invocation_id: str,
    plan_digest: str,
    stage_id: str,
    environment_digest: str,
    result: ProcessResult,
) -> tuple[dict[str, Any], dict[str, object]]:
    document = _stage_document(
        invocation_id=invocation_id,
        plan_digest=plan_digest,
        stage_id=stage_id,
        environment_digest=environment_digest,
        result=result,
    )
    filename = f"{stage_id}-stage.json"
    publish_no_replace(
        evidence_root / filename,
        canonical_document_bytes(document),
    )
    return document, {
        "stage_id": stage_id,
        "status": "ran",
        "result_path": filename,
        "result_digest": document["self_digest"],
        "outcome": result.outcome,
        "duration_ns": result.duration_ns,
    }


def _not_run_stage(stage_id: str) -> dict[str, object]:
    return {
        "stage_id": stage_id,
        "status": "not_run",
        "result_path": None,
        "result_digest": None,
        "outcome": "not_run",
        "duration_ns": 0,
    }


def _planner_digest() -> str:
    return sha256_digest(Path(__file__).read_bytes())


def _stage_plan(
    *,
    stage_id: str,
    argv: Sequence[str],
    cwd: Path,
    environment_digest: str,
    deadline_seconds: int,
) -> dict[str, object]:
    return {
        "stage_id": stage_id,
        "argv": list(argv),
        "cwd": str(cwd),
        "environment_digest": environment_digest,
        "deadline_seconds": deadline_seconds,
        "resource_class": "serial_unknown",
    }


def _load_stage_documents(
    output_root: Path,
    receipt: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    raw_stages = receipt.get("stages")
    if not isinstance(raw_stages, list):
        raise DiagnosticError("diagnostic receipt stages must be an array")
    for raw in raw_stages:
        if not isinstance(raw, dict) or raw.get("status") != "ran":
            continue
        stage_id = raw.get("stage_id")
        result_path = raw.get("result_path")
        if not isinstance(stage_id, str) or not isinstance(result_path, str):
            raise DiagnosticError("diagnostic ran stage lacks identity or result path")
        pure = PurePosixPath(result_path)
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
            raise DiagnosticError("diagnostic stage result path is unsafe")
        path = output_root / pure.as_posix()
        try:
            documents[stage_id] = load_canonical_document_bytes(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise DiagnosticError(
                f"cannot load diagnostic stage result {path}: {exc}"
            ) from exc
    return documents


def verify_diagnostic_documents(
    *,
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    stage_documents: Mapping[str, Mapping[str, Any]],
    current_source_identity_digest: str | None = None,
) -> None:
    """Purely verify one diagnostic plan/receipt/stage evidence closure."""

    try:
        verify_sealed_document(plan)
        verify_sealed_document(receipt)
    except ValueError as exc:
        raise DiagnosticError(f"invalid diagnostic evidence: {exc}") from exc
    if plan.get("schema_id") != EXECUTION_PLAN_SCHEMA_ID:
        raise DiagnosticError("diagnostic plan schema is invalid")
    if receipt.get("schema_id") != RECEIPT_SCHEMA_ID:
        raise DiagnosticError("diagnostic receipt schema is invalid")
    profile_id = plan.get("profile_id")
    if profile_id not in {"focused_diagnostic", "affected_scope_diagnostic"}:
        raise DiagnosticError("plan is not a diagnostic profile")
    if receipt.get("profile_id") != profile_id:
        raise DiagnosticError("diagnostic plan and receipt profiles differ")
    for document in (plan.get("authority"), receipt):
        if not isinstance(document, Mapping):
            raise DiagnosticError("diagnostic authority flags are missing")
        if (
            document.get("authoritative") is not False
            or document.get("admission_eligible") is not False
            or document.get("live_eligible") is not False
        ):
            raise DiagnosticError("diagnostic evidence attempted an authority upgrade")
    if receipt.get("plan_digest") != plan.get("self_digest"):
        raise DiagnosticError("diagnostic receipt plan digest mismatch")
    source_identity = plan.get("source_identity")
    if not isinstance(source_identity, dict):
        raise DiagnosticError("diagnostic plan source identity is missing")
    source_digest = sha256_digest(canonical_json_bytes(source_identity))
    if receipt.get("source_identity_digest") != source_digest:
        raise DiagnosticError("diagnostic receipt source identity mismatch")
    if (
        current_source_identity_digest is not None
        and current_source_identity_digest != source_digest
    ):
        raise DiagnosticError("diagnostic evidence source identity is stale")

    selection = plan.get("diagnostic_selection")
    receipt_selection = receipt.get("diagnostic_selection")
    if not isinstance(selection, dict) or not isinstance(receipt_selection, dict):
        raise DiagnosticError("diagnostic selection evidence is missing")
    expected_receipt_selection_fields = set(selection) | {
        "collection_observation_digest",
        "execution_observation_digest",
        "unexpected_deselected",
    }
    if set(receipt_selection) != expected_receipt_selection_fields:
        raise DiagnosticError("diagnostic receipt selection fields are incomplete")
    for field in selection:
        if receipt_selection.get(field) != selection.get(field):
            raise DiagnosticError(
                f"diagnostic receipt selection field {field!r} drifted"
            )
    inputs = selection.get("input")
    expanded = selection.get("expanded")
    frontend = selection.get("frontend")
    if not isinstance(inputs, dict) or not any(
        inputs.get(field)
        for field in (
            "lint_paths",
            "pytest_paths",
            "node_ids",
            "contract_groups",
            "changed_paths",
        )
    ):
        raise DiagnosticError("diagnostic input selection is empty")
    if not isinstance(frontend, dict):
        raise DiagnosticError("diagnostic frontend decision is missing")
    if not isinstance(expanded, dict) or not (
        expanded.get("lint_paths")
        or expanded.get("pytest_selectors")
        or frontend.get("included") is True
    ):
        raise DiagnosticError("diagnostic expanded selection is empty")
    if frontend.get("included") is False and frontend.get(
        "frontend_omission"
    ) != "diagnostic_only":
        raise DiagnosticError("diagnostic frontend omission is not explicit")
    deselection_policy = selection.get("collection_deselection_policy")
    policy_deselected = selection.get("policy_deselected_nodes")
    expected_deselection_policy = (
        "exclude_declared_non_live_markers"
        if profile_id == "affected_scope_diagnostic"
        else "reject_any"
    )
    if deselection_policy != expected_deselection_policy or not isinstance(
        policy_deselected, list
    ):
        raise DiagnosticError("diagnostic collection deselection policy drifted")
    seen_policy_deselected: list[str] = []
    for index, raw in enumerate(policy_deselected):
        if not isinstance(raw, dict) or set(raw) != {"node_id", "markers"}:
            raise DiagnosticError(
                f"diagnostic policy deselection {index} is malformed"
            )
        node_id = raw.get("node_id")
        markers = raw.get("markers")
        if (
            not isinstance(node_id, str)
            or not node_id
            or not isinstance(markers, list)
            or markers != sorted(set(markers))
            or not markers
            or not set(markers) <= FORBIDDEN_NON_LIVE_MARKERS
        ):
            raise DiagnosticError(
                f"diagnostic policy deselection {index} is invalid"
            )
        seen_policy_deselected.append(node_id)
    if seen_policy_deselected != sorted(set(seen_policy_deselected)):
        raise DiagnosticError(
            "diagnostic policy deselected node ids are not sorted and unique"
        )
    if profile_id == "focused_diagnostic" and policy_deselected:
        raise DiagnosticError(
            "focused diagnostic cannot contain policy deselections"
        )

    raw_ownership = plan.get("node_ownership")
    if not isinstance(raw_ownership, list):
        raise DiagnosticError("diagnostic node ownership is missing")
    planned_nodes = tuple(
        sorted(
            str(item["node_id"])
            for item in raw_ownership
            if isinstance(item, dict) and isinstance(item.get("node_id"), str)
        )
    )
    if len(planned_nodes) != len(raw_ownership):
        raise DiagnosticError("diagnostic node ownership contains invalid records")
    expected_coverage_digest = sha256_digest(
        canonical_json_bytes(list(planned_nodes))
    )
    if plan.get("expected_coverage_digest") != expected_coverage_digest:
        raise DiagnosticError("diagnostic plan coverage digest mismatch")
    coverage = receipt.get("coverage")
    if not isinstance(coverage, dict):
        raise DiagnosticError("diagnostic receipt coverage is missing")
    if tuple(coverage.get("collected_nodes", ())) != planned_nodes:
        raise DiagnosticError("diagnostic collected node closure drifted")
    executed_nodes = tuple(coverage.get("executed_nodes", ()))
    terminal_status = receipt.get("terminal_status")
    if terminal_status == "pass" and executed_nodes != planned_nodes:
        raise DiagnosticError("passing diagnostic did not execute every planned node")
    if receipt_selection.get("unexpected_deselected") != []:
        raise DiagnosticError("diagnostic receipt contains unexpected deselection")

    raw_plan_stages = plan.get("stages")
    raw_receipt_stages = receipt.get("stages")
    if not isinstance(raw_plan_stages, list) or not isinstance(
        raw_receipt_stages, list
    ):
        raise DiagnosticError("diagnostic stage closure is missing")
    plan_stage_ids = [
        item.get("stage_id") for item in raw_plan_stages if isinstance(item, dict)
    ]
    receipt_stage_ids = [
        item.get("stage_id")
        for item in raw_receipt_stages
        if isinstance(item, dict)
    ]
    if (
        len(plan_stage_ids) != len(raw_plan_stages)
        or any(
            not isinstance(stage_id, str) or not stage_id
            for stage_id in plan_stage_ids
        )
        or len(plan_stage_ids) != len(set(plan_stage_ids))
        or receipt_stage_ids != plan_stage_ids
    ):
        raise DiagnosticError("diagnostic receipt stage order drifted")
    collection_stage_id = (
        "affected_scope_pytest_collection"
        if profile_id == "affected_scope_diagnostic"
        else "focused_pytest_collection"
    )
    collection_plans = [
        item
        for item in raw_plan_stages
        if isinstance(item, dict) and item.get("stage_id") == collection_stage_id
    ]
    if expanded.get("collection_selectors"):
        if len(collection_plans) != 1:
            raise DiagnosticError("diagnostic collection stage is missing")
        collection_argv = collection_plans[0].get("argv")
        if not isinstance(collection_argv, list):
            raise DiagnosticError("diagnostic collection argv is missing")
        marker_positions = [
            index for index, value in enumerate(collection_argv) if value == "-m"
        ]
        if profile_id == "affected_scope_diagnostic":
            if (
                len(marker_positions) != 1
                or marker_positions[0] + 1 >= len(collection_argv)
                or collection_argv[marker_positions[0] + 1]
                != NON_LIVE_MARKER_EXPRESSION
            ):
                raise DiagnosticError(
                    "affected collection lacks the closed non-live marker policy"
                )
        elif marker_positions:
            raise DiagnosticError(
                "focused collection hid selector markers before validation"
            )
    elif collection_plans:
        raise DiagnosticError("diagnostic planned an unselected collection stage")

    expected_frontend_stage_ids = ["web_ui_test", "web_ui_build"]
    receipt_frontend = receipt.get("frontend")
    if not isinstance(receipt_frontend, dict):
        raise DiagnosticError("diagnostic frontend receipt is missing")
    if set(receipt_frontend) != set(frontend) | {"outcomes"}:
        raise DiagnosticError("diagnostic frontend receipt fields drifted")
    for field, value in frontend.items():
        if receipt_frontend.get(field) != value:
            raise DiagnosticError(
                f"diagnostic frontend receipt field {field!r} drifted"
            )
    frontend_outcomes = receipt_frontend.get("outcomes")
    if not isinstance(frontend_outcomes, dict):
        raise DiagnosticError("diagnostic frontend outcomes are missing")
    planned_frontend_stage_ids = [
        stage_id
        for stage_id in plan_stage_ids
        if stage_id in expected_frontend_stage_ids
    ]
    if frontend.get("included") is True:
        if (
            frontend.get("stage_ids") != expected_frontend_stage_ids
            or frontend.get("frontend_omission") is not None
            or planned_frontend_stage_ids != expected_frontend_stage_ids
            or plan_stage_ids[-2:] != expected_frontend_stage_ids
            or set(frontend_outcomes) != set(expected_frontend_stage_ids)
        ):
            raise DiagnosticError("diagnostic frontend stage closure drifted")
    elif (
        frontend.get("stage_ids") != []
        or planned_frontend_stage_ids
        or frontend_outcomes
    ):
        raise DiagnosticError("diagnostic frontend omission leaked stage evidence")
    plan_stages_by_id = {
        str(item["stage_id"]): item
        for item in raw_plan_stages
        if isinstance(item, dict)
    }
    blocked = False
    for raw in raw_receipt_stages:
        if not isinstance(raw, dict):
            raise DiagnosticError("diagnostic receipt stage record is invalid")
        stage_id = raw["stage_id"]
        status = raw.get("status")
        if status == "not_run":
            if not blocked:
                raise DiagnosticError(
                    "diagnostic stage was omitted without an earlier failure"
                )
            if any(
                raw.get(field) is not None
                for field in ("result_path", "result_digest")
            ):
                raise DiagnosticError("not-run diagnostic stage references output")
            continue
        if status != "ran":
            raise DiagnosticError("diagnostic stage status is invalid")
        planned_stage = plan_stages_by_id[str(stage_id)]
        document = stage_documents.get(str(stage_id))
        if document is None:
            raise DiagnosticError(f"diagnostic stage output is missing: {stage_id}")
        try:
            verify_sealed_document(document)
        except ValueError as exc:
            raise DiagnosticError(
                f"invalid diagnostic stage output {stage_id}: {exc}"
            ) from exc
        if (
            document.get("schema_id") != STAGE_RESULT_SCHEMA_ID
            or document.get("invocation_id") != receipt.get("invocation_id")
            or document.get("plan_digest") != plan.get("self_digest")
            or document.get("stage_id") != stage_id
            or document.get("self_digest") != raw.get("result_digest")
            or document.get("outcome") != raw.get("outcome")
            or document.get("duration_ns") != raw.get("duration_ns")
            or document.get("argv") != planned_stage.get("argv")
            or document.get("cwd") != planned_stage.get("cwd")
            or document.get("environment_digest")
            != planned_stage.get("environment_digest")
        ):
            raise DiagnosticError(f"diagnostic stage output drifted: {stage_id}")
        if stage_id in expected_frontend_stage_ids and (
            frontend_outcomes.get(stage_id) != raw.get("outcome")
        ):
            raise DiagnosticError(
                f"diagnostic frontend outcome drifted: {stage_id}"
            )
        if raw.get("outcome") != "pass":
            blocked = True
    expected_terminal = (
        "pass"
        if all(
            isinstance(item, dict)
            and item.get("status") == "ran"
            and item.get("outcome") == "pass"
            for item in raw_receipt_stages
        )
        else "fail"
    )
    if terminal_status != expected_terminal:
        raise DiagnosticError("diagnostic terminal status does not match stages")


def verify_diagnostic_output(
    *,
    plan_path: Path,
    receipt_path: Path,
    current_source_identity_digest: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and purely verify a published diagnostic output."""

    try:
        plan = load_canonical_document_bytes(plan_path.read_bytes())
        receipt = load_canonical_document_bytes(receipt_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise DiagnosticError(f"cannot load diagnostic plan/receipt: {exc}") from exc
    if plan_path.parent.resolve() != receipt_path.parent.resolve():
        raise DiagnosticError("diagnostic plan and receipt must share one output root")
    stages = _load_stage_documents(receipt_path.parent.resolve(), receipt)
    verify_diagnostic_documents(
        plan=plan,
        receipt=receipt,
        stage_documents=stages,
        current_source_identity_digest=current_source_identity_digest,
    )
    return plan, receipt


def _run_diagnostic(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    profile_id: str,
    stage_prefix: str,
    selection_document: Mapping[str, Any],
    lint_paths: Sequence[str],
    collection_selectors: Sequence[str],
    planner_digest: str,
    process_runner: Callable[..., ProcessResult],
    source_collector: Callable[[Path], SourceIdentity],
    source_before: SourceIdentity | None = None,
) -> DiagnosticRunResult:
    """Execute one already-expanded diagnostic selection."""

    started = time.monotonic_ns()
    root = repo_root.resolve(strict=True)
    profile = config.profile(profile_id)
    if profile.authoritative or profile.admission_eligible or profile.live_eligible:
        raise DiagnosticError(f"{profile_id} attempted an authority upgrade")
    if source_before is None:
        source_before = source_collector(root)
    selection_payload = dict(selection_document)
    frontend_decision = selection_payload.get("frontend")
    if not isinstance(frontend_decision, Mapping):
        raise DiagnosticError("diagnostic selection lacks a frontend decision")
    expected_deselection_policy = (
        "exclude_declared_non_live_markers"
        if profile_id == "affected_scope_diagnostic"
        else "reject_any"
    )
    if (
        selection_payload.get("collection_deselection_policy")
        != expected_deselection_policy
        or selection_payload.get("policy_deselected_nodes") != []
    ):
        raise DiagnosticError(
            f"{profile_id} has an invalid collection deselection policy"
        )
    frontend_included = frontend_decision.get("included") is True
    if not lint_paths and not collection_selectors and not frontend_included:
        raise DiagnosticError("diagnostic selection expanded to zero checks")

    evidence_root = create_new_output_root(root, output_root)
    environment = diagnostic_environment(root)
    environment_digest = sha256_digest(canonical_json_bytes(environment))
    collection_stage_id = f"{stage_prefix}_pytest_collection"
    lint_stage_id = f"{stage_prefix}_ruff"
    execution_stage_id = f"{stage_prefix}_pytest_execution"
    collection_result: ProcessResult | None = None
    collection_observation: _Observation | None = None
    collection_argv: tuple[str, ...] | None = None
    exact_nodes: tuple[str, ...] = ()

    if collection_selectors:
        collection_path = evidence_root / f"{stage_prefix}-collection.json"
        collection_argv = (
            *_pytest_prefix(),
            "--collect-only",
            *(
                ("-m", NON_LIVE_MARKER_EXPRESSION)
                if profile_id == "affected_scope_diagnostic"
                else ()
            ),
            *collection_selectors,
            *_observation_arguments(
                output_path=collection_path,
                invocation_id=invocation_id,
                role=profile_id,
                mode="collect",
            ),
        )
        collection_result = process_runner(
            collection_argv,
            cwd=root,
            environment=environment,
            timeout_seconds=300.0,
        )
        if collection_result.outcome != "pass":
            raise DiagnosticError(
                f"{profile_id} collection failed: "
                f"{collection_result.stderr.tail}"
            )
        collection_observation = _load_observation(
            collection_path,
            invocation_id=invocation_id,
            role=profile_id,
            mode="collect",
        )
        forbidden = _forbidden_nodes(collection_observation.snapshot)
        if forbidden:
            details = ", ".join(
                f"{item['node_id']}[{','.join(item['markers'])}]"
                for item in forbidden
            )
            raise DiagnosticError(
                "diagnostic selector resolved to forbidden live/integration "
                f"nodes: {details}"
            )
        raw_collection_deselected = tuple(
            collection_observation.document["deselected"]
        )
        if profile_id == "focused_diagnostic" and raw_collection_deselected:
            raise DiagnosticError(
                "focused diagnostic collection unexpectedly deselected nodes: "
                + ", ".join(raw_collection_deselected)
            )
        if profile_id == "affected_scope_diagnostic":
            selection_payload["policy_deselected_nodes"] = list(
                _classified_policy_deselections(collection_observation)
            )
        exact_nodes = collection_observation.snapshot.nodes
        if not exact_nodes and not lint_paths and not frontend_included:
            raise DiagnosticError("diagnostic collection resolved to zero nodes")
        _assert_source_unchanged(
            source_before,
            root,
            collector=source_collector,
        )

    lint_argv = (
        ("uv", "run", "ruff", "check", *lint_paths) if lint_paths else None
    )
    execution_path = evidence_root / f"{stage_prefix}-execution.json"
    execution_argv = (
        (
            *_pytest_prefix(),
            "-m",
            NON_LIVE_MARKER_EXPRESSION,
            *exact_nodes,
            *_observation_arguments(
                output_path=execution_path,
                invocation_id=invocation_id,
                role=profile_id,
                mode="execute",
            ),
        )
        if exact_nodes
        else None
    )
    frontend_commands = (
        (
            ("web_ui_test", ("npm", "test")),
            ("web_ui_build", ("npm", "run", "build")),
        )
        if frontend_included
        else ()
    )
    web_ui_root = root / "apps/openzyme-web-ui"
    stage_plans: list[dict[str, object]] = []
    if collection_argv is not None:
        stage_plans.append(
            _stage_plan(
                stage_id=collection_stage_id,
                argv=collection_argv,
                cwd=root,
                environment_digest=environment_digest,
                deadline_seconds=300,
            )
        )
    if lint_argv is not None:
        stage_plans.append(
            _stage_plan(
                stage_id=lint_stage_id,
                argv=lint_argv,
                cwd=root,
                environment_digest=environment_digest,
                deadline_seconds=300,
            )
        )
    if execution_argv is not None:
        stage_plans.append(
            _stage_plan(
                stage_id=execution_stage_id,
                argv=execution_argv,
                cwd=root,
                environment_digest=environment_digest,
                deadline_seconds=1800,
            )
        )
    for stage_id, argv in frontend_commands:
        stage_plans.append(
            _stage_plan(
                stage_id=stage_id,
                argv=argv,
                cwd=web_ui_root,
                environment_digest=environment_digest,
                deadline_seconds=300,
            )
        )
    plan = seal_document(
        EXECUTION_PLAN_SCHEMA_ID,
        {
            "invocation_id": invocation_id,
            "profile_id": profile.id,
            "planner_digest": planner_digest,
            "config_digest": config.digest,
            "source_identity": source_before.as_dict(),
            "toolchains": [
                identity.as_dict() for identity in source_before.toolchains
            ],
            "output_root": str(evidence_root),
            "stages": stage_plans,
            "node_ownership": [
                {"node_id": node_id, "owner": profile.id}
                for node_id in exact_nodes
            ],
            "expected_coverage_digest": sha256_digest(
                canonical_json_bytes(list(exact_nodes))
            ),
            "worker_policy": {
                "mode": "forced_serial",
                "workers": 1,
                "hard_max": config.worker_hard_max,
            },
            "authority": {
                "authoritative": False,
                "admission_eligible": False,
                "live_eligible": False,
                "authority_domain": "diagnostic_only",
            },
            "collections": {
                "pytest": (
                    None
                    if collection_observation is None
                    else {
                        "observation_digest": (
                            collection_observation.document_digest
                        ),
                        "collection_digest": (
                            collection_observation.snapshot.digest
                        ),
                        "nodes": list(exact_nodes),
                    }
                )
            },
            "diagnostic_selection": selection_payload,
            "source_recheck_policy": "after_collection_each_stage_and_final",
        },
    )
    publish_no_replace(
        evidence_root / "diagnostic-plan.json",
        canonical_document_bytes(plan),
    )
    plan_digest = str(plan["self_digest"])
    stage_documents: dict[str, dict[str, Any]] = {}
    receipt_stages: list[dict[str, object]] = []

    if collection_result is not None:
        stage_document, stage_record = _publish_stage(
            evidence_root=evidence_root,
            invocation_id=invocation_id,
            plan_digest=plan_digest,
            stage_id=collection_stage_id,
            environment_digest=environment_digest,
            result=collection_result,
        )
        stage_documents[collection_stage_id] = stage_document
        receipt_stages.append(stage_record)

    blocked = False
    if lint_argv is not None:
        lint_result = process_runner(
            lint_argv,
            cwd=root,
            environment=environment,
            timeout_seconds=300.0,
        )
        stage_document, stage_record = _publish_stage(
            evidence_root=evidence_root,
            invocation_id=invocation_id,
            plan_digest=plan_digest,
            stage_id=lint_stage_id,
            environment_digest=environment_digest,
            result=lint_result,
        )
        stage_documents[lint_stage_id] = stage_document
        receipt_stages.append(stage_record)
        blocked = lint_result.outcome != "pass"
        _assert_source_unchanged(
            source_before,
            root,
            collector=source_collector,
        )

    execution_observation: _Observation | None = None
    if execution_argv is not None and not blocked:
        execution_result = process_runner(
            execution_argv,
            cwd=root,
            environment=environment,
            timeout_seconds=1800.0,
        )
        if not execution_path.is_file():
            raise DiagnosticError(
                "diagnostic pytest execution did not publish its observation"
            )
        execution_observation = _load_observation(
            execution_path,
            invocation_id=invocation_id,
            role=profile_id,
            mode="execute",
        )
        if execution_observation.snapshot.nodes != exact_nodes:
            raise DiagnosticError(
                "diagnostic execution collection drifted from its plan"
            )
        deselected = execution_observation.document["deselected"]
        if deselected:
            raise DiagnosticError(
                "diagnostic execution unexpectedly deselected nodes: "
                + ", ".join(str(item) for item in deselected)
            )
        result_nodes = tuple(
            item["node_id"]
            for item in execution_observation.document["node_results"]
        )
        if result_nodes != exact_nodes:
            raise DiagnosticError(
                "diagnostic execution did not produce one result per planned node"
            )
        stage_document, stage_record = _publish_stage(
            evidence_root=evidence_root,
            invocation_id=invocation_id,
            plan_digest=plan_digest,
            stage_id=execution_stage_id,
            environment_digest=environment_digest,
            result=execution_result,
        )
        stage_documents[execution_stage_id] = stage_document
        receipt_stages.append(stage_record)
        blocked = execution_result.outcome != "pass"
        _assert_source_unchanged(
            source_before,
            root,
            collector=source_collector,
        )
    elif execution_argv is not None:
        receipt_stages.append(_not_run_stage(execution_stage_id))

    frontend_outcomes: dict[str, str] = {}
    for stage_id, argv in frontend_commands:
        if blocked:
            receipt_stages.append(_not_run_stage(stage_id))
            frontend_outcomes[stage_id] = "not_run"
            continue
        result = process_runner(
            argv,
            cwd=web_ui_root,
            environment=environment,
            timeout_seconds=300.0,
        )
        stage_document, stage_record = _publish_stage(
            evidence_root=evidence_root,
            invocation_id=invocation_id,
            plan_digest=plan_digest,
            stage_id=stage_id,
            environment_digest=environment_digest,
            result=result,
        )
        stage_documents[stage_id] = stage_document
        receipt_stages.append(stage_record)
        frontend_outcomes[stage_id] = result.outcome
        blocked = result.outcome != "pass"
        _assert_source_unchanged(
            source_before,
            root,
            collector=source_collector,
        )

    _assert_source_unchanged(
        source_before,
        root,
        collector=source_collector,
    )
    terminal_status = "fail" if blocked else "pass"
    receipt_selection = {
        **selection_payload,
        "collection_observation_digest": (
            None
            if collection_observation is None
            else collection_observation.document_digest
        ),
        "execution_observation_digest": (
            None
            if execution_observation is None
            else execution_observation.document_digest
        ),
        "unexpected_deselected": [],
    }
    executed_nodes = (
        []
        if execution_observation is None
        else list(execution_observation.snapshot.nodes)
    )
    node_results = (
        []
        if execution_observation is None
        else list(execution_observation.document["node_results"])
    )
    receipt = seal_document(
        RECEIPT_SCHEMA_ID,
        {
            "invocation_id": invocation_id,
            "profile_id": profile.id,
            "authoritative": False,
            "admission_eligible": False,
            "live_eligible": False,
            "plan_digest": plan_digest,
            "source_identity_digest": source_before.digest,
            "stages": receipt_stages,
            "terminal_status": terminal_status,
            "coverage": {
                "collected_nodes": list(exact_nodes),
                "executed_nodes": executed_nodes,
                "node_results": node_results,
                "collection_digest": sha256_digest(
                    canonical_json_bytes(list(exact_nodes))
                ),
            },
            "diagnostic_selection": receipt_selection,
            "frontend": {
                **dict(frontend_decision),
                "outcomes": frontend_outcomes,
            },
            "resource_assignments": {
                "workers": 1,
                "resource_class": "serial_unknown",
            },
            "timing": {
                "total_duration_ns": max(0, time.monotonic_ns() - started),
                "stage_duration_ns": {
                    str(item["stage_id"]): int(item["duration_ns"])
                    for item in receipt_stages
                },
            },
        },
    )
    verify_diagnostic_documents(
        plan=plan,
        receipt=receipt,
        stage_documents=stage_documents,
        current_source_identity_digest=source_before.digest,
    )
    publish_no_replace(
        evidence_root / "diagnostic-receipt.json",
        canonical_document_bytes(receipt),
    )
    return DiagnosticRunResult(
        output_root=evidence_root,
        plan=plan,
        receipt=receipt,
        terminal_status=terminal_status,
    )


def run_focused_diagnostic(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    lint_paths: Sequence[str] = (),
    pytest_paths: Sequence[str] = (),
    node_ids: Sequence[str] = (),
    contract_groups: Sequence[str] = (),
    process_runner: Callable[..., ProcessResult] = run_command,
    source_collector: Callable[[Path], SourceIdentity] = collect_source_identity,
) -> DiagnosticRunResult:
    """Plan, execute, publish, and verify one focused non-live diagnostic."""

    root = repo_root.resolve(strict=True)
    selection = expand_focused_selection(
        root,
        lint_paths=lint_paths,
        pytest_paths=pytest_paths,
        node_ids=node_ids,
        contract_groups=contract_groups,
    )
    return _run_diagnostic(
        repo_root=root,
        output_root=output_root,
        config=config,
        invocation_id=invocation_id,
        profile_id="focused_diagnostic",
        stage_prefix="focused",
        selection_document=selection.as_plan_dict(),
        lint_paths=selection.lint_paths,
        collection_selectors=selection.collection_selectors,
        planner_digest=_planner_digest(),
        process_runner=process_runner,
        source_collector=source_collector,
    )
