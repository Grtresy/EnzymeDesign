"""Fail-fast mainline process execution and pure receipt closure."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from .authoritative import (
    AuthoritativePlanError,
    GENERAL_EXECUTION_OBSERVATION_FILENAME,
    GENERAL_RECHECK_OBSERVATION_FILENAME,
    MAINLINE_AUTHORITATIVE_PLAN_FILENAME,
    NODE_MANIFEST_FILENAME,
    PLAN_FILENAME,
    QUALIFICATION_REPORT_FILENAME,
    QUALIFICATION_SIDECAR_FILENAME,
    AuthoritativePlanResult,
    run_authoritative_mainline_plan,
    run_authoritative_shadow_plan,
    stage_environments,
    verify_authoritative_plan,
    verify_node_manifest,
)
from .config import TestGateConfig
from .resource import DEFAULT_RESOURCE_MANIFEST_PATH
from .model import (
    RECEIPT_SCHEMA_ID,
    QUALIFICATION_SIDECAR_SCHEMA_ID,
    PYTEST_OBSERVATION_SCHEMA_ID,
    STAGE_RESULT_SCHEMA_ID,
    canonical_document_bytes,
    canonical_json_bytes,
    load_canonical_document_bytes,
    seal_document,
    sha256_digest,
    verify_sealed_document,
)
from .partition import (
    GeneralPartitionError,
    verify_general_partition_bundle,
)
from .runner import ProcessResult, publish_no_replace, run_command
from .source import SourceIdentity, collect_source_identity

_STAGE_RECEIPT_FIELDS = {
    "stage_id",
    "status",
    "result_path",
    "result_digest",
    "outcome",
    "duration_ns",
}
_NODE_RESULT_FIELDS = {
    "node_id",
    "owner",
    "outcome",
    "duration_ns",
}
_COVERAGE_FIELDS = {
    "collected_nodes",
    "owned_nodes_digest",
    "executed_nodes",
    "node_results",
    "unexpected_deselected",
    "collection_digest",
    "general_recheck_observation_digest",
    "general_execution_observation_digest",
    "manifest_digest",
}
_FRONTEND_FIELDS = {"required_stage_ids", "outcomes"}
_QUALIFICATION_FIELDS = {
    "status",
    "sidecar_path",
    "sidecar_digest",
    "report_digest",
    "harness_nodes",
    "scenario_nodes",
    "node_results_digest",
}
_RESOURCE_FIELDS = {
    "mode",
    "workers",
    "hard_max",
    "assignments_digest",
}
_TIMING_FIELDS = {"total_duration_ns", "stage_duration_ns"}
_STAGE_OUTCOMES = {"pass", "fail", "timeout", "error"}
_NODE_OUTCOMES = {
    "pass",
    "fail",
    "skip",
    "xfail",
    "xpass",
    "timeout",
    "error",
}
_GENERAL_PASS_OUTCOMES = {"pass", "skip", "xfail", "xpass"}
_QUALIFICATION_SIDECAR_FIELDS = {
    "schema_id",
    "invocation_id",
    "plan_digest",
    "source_identity_digest",
    "environment_digest",
    "qualification_report_digest",
    "qualification_report_path",
    "node_results",
    "harness_collection",
    "scenario_collection",
    "qualification_mode",
    "self_digest",
}
_QUALIFICATION_NODE_FIELDS = {
    "duration_ns",
    "markers",
    "node_id",
    "outcome",
    "phases",
}
MAINLINE_CANDIDATE_RECEIPT_FILENAME = "mainline-candidate-receipt.json"
MAINLINE_AUTHORITATIVE_RECEIPT_FILENAME = "mainline-authoritative-receipt.json"
_MAINLINE_SIDECAR_OUTPUT_ENV = "OPENZYME_MAINLINE_QUALIFICATION_SIDECAR"
_MAINLINE_INVOCATION_ID_ENV = "OPENZYME_MAINLINE_INVOCATION_ID"
_MAINLINE_PLAN_DIGEST_ENV = "OPENZYME_MAINLINE_PLAN_DIGEST"
_MAINLINE_SOURCE_DIGEST_ENV = "OPENZYME_MAINLINE_SOURCE_DIGEST"
_MAINLINE_ENVIRONMENT_DIGEST_ENV = "OPENZYME_MAINLINE_ENVIRONMENT_DIGEST"


class AuthoritativeRunnerError(RuntimeError):
    """Raised when candidate execution or receipt closure fails."""


@dataclass(frozen=True)
class StageSequenceResult:
    """One fail-fast stage sequence and its canonical result documents."""

    receipt_stages: tuple[Mapping[str, Any], ...]
    stage_documents: Mapping[str, Mapping[str, Any]]
    first_failing_stage: str | None


@dataclass(frozen=True)
class MainlineCandidateRunResult:
    """One published shadow candidate receipt and its plan evidence."""

    output_root: Path
    plan: Mapping[str, Any]
    manifest: Mapping[str, Any]
    receipt: Mapping[str, Any]
    terminal_status: str


@dataclass(frozen=True)
class MainlineCandidateVerificationResult:
    """One independently reloaded and recomputed candidate evidence bundle."""

    output_root: Path
    plan: Mapping[str, Any]
    manifest: Mapping[str, Any]
    receipt: Mapping[str, Any]


def _load_candidate_document(
    path: Path,
    *,
    context: str,
) -> dict[str, Any]:
    if path.is_symlink():
        raise AuthoritativeRunnerError(f"{context} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise AuthoritativeRunnerError(f"{context} is missing") from exc
    if resolved != path or not resolved.is_file():
        raise AuthoritativeRunnerError(f"{context} path is not exact")
    try:
        return load_canonical_document_bytes(resolved.read_bytes())
    except (OSError, ValueError) as exc:
        raise AuthoritativeRunnerError(f"{context} is invalid: {exc}") from exc


def _candidate_output_root(
    *,
    output_root: Path,
    repo_root: Path,
) -> Path:
    if not output_root.is_absolute() or output_root.is_symlink():
        raise AuthoritativeRunnerError(
            "candidate output root must be an absolute non-symlink"
        )
    try:
        resolved = output_root.resolve(strict=True)
        checkout = repo_root.resolve(strict=True)
    except OSError as exc:
        raise AuthoritativeRunnerError(
            "candidate output root or checkout is unavailable"
        ) from exc
    if resolved != output_root or not resolved.is_dir():
        raise AuthoritativeRunnerError("candidate output root path is not exact")
    try:
        resolved.relative_to(checkout)
    except ValueError:
        return resolved
    raise AuthoritativeRunnerError(
        "candidate output root must remain outside the checkout"
    )


def _strict_mapping(
    value: Any,
    *,
    fields: set[str],
    context: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise AuthoritativeRunnerError(
            f"{context} must contain exactly {sorted(fields)!r}"
        )
    return value


def _sorted_unique_strings(value: Any, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise AuthoritativeRunnerError(f"{context} must be an array of strings")
    result = tuple(value)
    if result != tuple(sorted(set(result))):
        raise AuthoritativeRunnerError(f"{context} must be sorted and unique")
    return result


def _stage_result_document(
    *,
    invocation_id: str,
    plan_digest: str,
    stage: Mapping[str, Any],
    result: ProcessResult,
) -> dict[str, Any]:
    return seal_document(
        STAGE_RESULT_SCHEMA_ID,
        {
            "invocation_id": invocation_id,
            "plan_digest": plan_digest,
            "stage_id": stage["stage_id"],
            "argv": list(result.argv),
            "cwd": result.cwd,
            "environment_digest": stage["environment_digest"],
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


def _ran_stage_record(
    *,
    stage_id: str,
    result_path: str,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "status": "ran",
        "result_path": result_path,
        "result_digest": document["self_digest"],
        "outcome": document["outcome"],
        "duration_ns": document["duration_ns"],
    }


def _not_run_stage_record(stage_id: str) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "status": "not_run",
        "result_path": None,
        "result_digest": None,
        "outcome": "not_run",
        "duration_ns": 0,
    }


def run_fail_fast_stage_sequence(
    *,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    repo_root: Path,
    config: TestGateConfig,
    environments: Mapping[str, Mapping[str, str]],
    process_runner: Callable[..., ProcessResult] = run_command,
    source_collector: Callable[[Path], SourceIdentity] = collect_source_identity,
    before_stage: Callable[[str], None] | None = None,
    environment_transform: Callable[
        [str, Mapping[str, str]], Mapping[str, str]
    ]
    | None = None,
    expected_authoritative: bool = False,
) -> StageSequenceResult:
    """Execute planned process stages in order and never cross a failure."""

    root = repo_root.resolve(strict=True)
    expected_source = sha256_digest(
        canonical_json_bytes(plan["source_identity"])
    )
    verify_authoritative_plan(
        plan,
        repo_root=root,
        config=config,
        current_source_identity_digest=source_collector(root).digest,
        current_environments=environments,
        expected_authoritative=expected_authoritative,
    )
    verify_node_manifest(manifest, plan=plan)
    output_root = Path(str(plan["output_root"]))
    stages = plan["stages"]
    if not isinstance(stages, list):
        raise AuthoritativeRunnerError("authoritative plan stages are missing")
    receipt_stages: list[Mapping[str, Any]] = []
    stage_documents: dict[str, Mapping[str, Any]] = {}
    first_failing_stage: str | None = None
    for index, stage in enumerate(stages):
        stage_id = str(stage["stage_id"])
        if first_failing_stage is not None:
            receipt_stages.append(_not_run_stage_record(stage_id))
            continue
        if source_collector(root).digest != expected_source:
            raise AuthoritativeRunnerError(
                f"source identity drifted before stage {stage_id}"
            )
        if before_stage is not None:
            before_stage(stage_id)
        environment = environments.get(stage_id)
        if environment is None:
            raise AuthoritativeRunnerError(
                f"stage environment is missing for {stage_id}"
            )
        execution_environment = (
            environment
            if environment_transform is None
            else environment_transform(stage_id, environment)
        )
        result = process_runner(
            tuple(stage["argv"]),
            cwd=Path(str(stage["cwd"])),
            environment=execution_environment,
            timeout_seconds=float(stage["deadline_seconds"]),
        )
        result_path = f"{index + 1:02d}-{stage_id}-stage.json"
        document = _stage_result_document(
            invocation_id=str(plan["invocation_id"]),
            plan_digest=str(plan["self_digest"]),
            stage=stage,
            result=result,
        )
        publish_no_replace(
            output_root / result_path,
            canonical_document_bytes(document),
        )
        stage_documents[stage_id] = document
        receipt_stages.append(
            _ran_stage_record(
                stage_id=stage_id,
                result_path=result_path,
                document=document,
            )
        )
        if result.outcome != "pass":
            first_failing_stage = stage_id
    if source_collector(root).digest != expected_source:
        raise AuthoritativeRunnerError(
            "source identity drifted after the stage sequence"
        )
    return StageSequenceResult(
        receipt_stages=tuple(receipt_stages),
        stage_documents=stage_documents,
        first_failing_stage=first_failing_stage,
    )


def _normalize_node_results(
    value: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        record = _strict_mapping(
            raw,
            fields=_NODE_RESULT_FIELDS,
            context=f"node_results[{index}]",
        )
        node_id = record["node_id"]
        owner = record["owner"]
        outcome = record["outcome"]
        duration_ns = record["duration_ns"]
        if not isinstance(node_id, str) or not node_id:
            raise AuthoritativeRunnerError("node result id must be nonempty")
        if owner not in {
            "architecture_qualification_premerge",
            "general_non_live_pytest",
        }:
            raise AuthoritativeRunnerError(
                f"node result {node_id!r} has an unknown owner"
            )
        if outcome not in _NODE_OUTCOMES:
            raise AuthoritativeRunnerError(
                f"node result {node_id!r} has an unknown outcome"
            )
        if type(duration_ns) is not int or duration_ns < 0:
            raise AuthoritativeRunnerError(
                f"node result {node_id!r} has invalid duration"
            )
        results.append(dict(record))
    results.sort(key=lambda item: item["node_id"])
    node_ids = [str(item["node_id"]) for item in results]
    if node_ids != sorted(set(node_ids)):
        raise AuthoritativeRunnerError(
            "node results contain duplicate node ids"
        )
    return results


def _load_pytest_observation_document(
    path: Path,
    *,
    invocation_id: str,
    role: str,
    mode: str,
) -> dict[str, Any]:
    try:
        document = load_canonical_document_bytes(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise AuthoritativeRunnerError(
            f"pytest observation is invalid or missing: {path}: {exc}"
        ) from exc
    if (
        document.get("schema_id") != PYTEST_OBSERVATION_SCHEMA_ID
        or document.get("invocation_id") != invocation_id
        or document.get("role") != role
        or document.get("mode") != mode
    ):
        raise AuthoritativeRunnerError(
            "pytest observation schema, invocation, role, or mode drifted"
        )
    return document


def _plan_collection_records(
    snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "node_id": str(item["node_id"]),
            "markers": list(item["markers"]),
        }
        for item in snapshot["markers"]
    ]


def load_and_verify_general_recheck(
    *,
    plan: Mapping[str, Any],
    observation_path: Path,
) -> str:
    """Close the mandatory same-invocation recollection of the full G set."""

    document = _load_pytest_observation_document(
        observation_path,
        invocation_id=str(plan["invocation_id"]),
        role="legacy_general",
        mode="collect",
    )
    general = plan["collections"]["general"]
    if (
        document["collection"] != _plan_collection_records(general)
        or document["deselected"]
        != [
            item["node_id"] for item in general["policy_deselected_nodes"]
        ]
        or document.get("deselected_markers")
        != general["policy_deselected_nodes"]
        or document["node_results"] != []
        or document["session_exit_code"] != 0
    ):
        raise AuthoritativeRunnerError(
            "same-invocation G recollection drifted from the plan"
        )
    return str(document["self_digest"])


def load_and_verify_general_execution(
    *,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    observation_path: Path,
) -> tuple[list[dict[str, Any]], str]:
    """Close exact residual execution and reject every unplanned deselection."""

    document = _load_pytest_observation_document(
        observation_path,
        invocation_id=str(plan["invocation_id"]),
        role="general_residual",
        mode="execute",
    )
    collections = plan["collections"]
    general = collections["general"]
    general_records = _plan_collection_records(general)
    general_markers = {
        item["node_id"]: list(item["markers"]) for item in general_records
    }
    residual_nodes = tuple(manifest["selected_nodes"])
    qualification_nodes = tuple(manifest["planned_deselected_nodes"])
    expected_residual = [
        {"node_id": node_id, "markers": general_markers[node_id]}
        for node_id in residual_nodes
    ]
    policy_records = [
        dict(item) for item in general["policy_deselected_nodes"]
    ]
    qualification_records = [
        {"node_id": node_id, "markers": general_markers[node_id]}
        for node_id in qualification_nodes
    ]
    expected_deselected_records = sorted(
        [*policy_records, *qualification_records],
        key=lambda item: str(item["node_id"]),
    )
    expected_deselected_ids = [
        str(item["node_id"]) for item in expected_deselected_records
    ]
    if (
        document.get("preselection_collection") != general_records
        or document["collection"] != expected_residual
        or document.get("planned_deselected") != list(qualification_nodes)
        or document["deselected"] != expected_deselected_ids
        or document.get("deselected_markers")
        != expected_deselected_records
        or document.get("selection_manifest_digest")
        != manifest["self_digest"]
        or document["session_exit_code"] != 0
    ):
        raise AuthoritativeRunnerError(
            "general residual execution collection or deselection drifted"
        )
    raw_results = document["node_results"]
    if not isinstance(raw_results, list):
        raise AuthoritativeRunnerError(
            "general residual node results are missing"
        )
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_results):
        record = _strict_mapping(
            raw,
            fields={"node_id", "outcome", "duration_ns", "phases"},
            context=f"general node_results[{index}]",
        )
        node_id = record["node_id"]
        outcome = record["outcome"]
        duration_ns = record["duration_ns"]
        if (
            not isinstance(node_id, str)
            or outcome not in _GENERAL_PASS_OUTCOMES
            or type(duration_ns) is not int
            or duration_ns < 0
            or not isinstance(record["phases"], list)
        ):
            raise AuthoritativeRunnerError(
                f"general residual node result {index} is invalid"
            )
        normalized.append(
            {
                "node_id": node_id,
                "owner": "general_non_live_pytest",
                "outcome": outcome,
                "duration_ns": duration_ns,
            }
        )
    normalized.sort(key=lambda item: item["node_id"])
    if tuple(item["node_id"] for item in normalized) != residual_nodes:
        raise AuthoritativeRunnerError(
            "general residual did not execute every manifest node exactly once"
        )
    return normalized, str(document["self_digest"])


def _verify_qualification_report_subprocess(
    report_path: Path,
    repo_root: Path,
) -> Mapping[str, Any]:
    completed = subprocess.run(
        (
            "uv",
            "run",
            "python",
            "scripts/verify-v3-architecture-qualification.py",
            str(report_path),
            "--repo-root",
            str(repo_root),
        ),
        cwd=repo_root,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if completed.returncode != 0:
        stderr = completed.stderr[-4000:].decode(
            "utf-8",
            errors="replace",
        )
        raise ValueError(
            "canonical qualification report verifier failed: " + stderr
        )
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "canonical qualification report verifier returned invalid JSON"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {
        "admission_eligible",
        "payload_digest",
        "rejection_reasons",
        "source_commit",
        "valid",
    }:
        raise ValueError(
            "canonical qualification report verifier result is not closed"
        )
    return payload


def load_and_verify_qualification_sidecar(
    *,
    plan: Mapping[str, Any],
    sidecar_path: Path,
    repo_root: Path,
    report_verifier: Callable[[Path, Path], Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Verify same-invocation Qh/Qs outcomes and the canonical report binding."""

    descriptor = plan["collections"]["qualification_sidecar"]
    output_root = Path(str(plan["output_root"]))
    expected_sidecar_path = output_root / str(descriptor["path"])
    try:
        actual_sidecar_path = sidecar_path.resolve(strict=True)
    except OSError as exc:
        raise AuthoritativeRunnerError(
            "qualification sidecar is missing"
        ) from exc
    if (
        actual_sidecar_path != expected_sidecar_path
        or actual_sidecar_path.name != QUALIFICATION_SIDECAR_FILENAME
    ):
        raise AuthoritativeRunnerError(
            "qualification sidecar path drifted from the plan"
        )
    try:
        sidecar = load_canonical_document_bytes(
            actual_sidecar_path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise AuthoritativeRunnerError(
            f"qualification sidecar is invalid: {exc}"
        ) from exc
    _strict_mapping(
        sidecar,
        fields=_QUALIFICATION_SIDECAR_FIELDS,
        context="qualification sidecar",
    )
    if sidecar["schema_id"] != QUALIFICATION_SIDECAR_SCHEMA_ID:
        raise AuthoritativeRunnerError(
            "qualification sidecar schema is invalid"
        )
    qualification_stage = next(
        (
            stage
            for stage in plan["stages"]
            if stage["stage_id"] == "architecture_qualification_premerge"
        ),
        None,
    )
    if qualification_stage is None:
        raise AuthoritativeRunnerError(
            "qualification stage is missing from the plan"
        )
    expected_source_digest = sha256_digest(
        canonical_json_bytes(plan["source_identity"])
    )
    bindings = {
        "invocation_id": plan["invocation_id"],
        "plan_digest": plan["self_digest"],
        "source_identity_digest": expected_source_digest,
        "environment_digest": qualification_stage["environment_digest"],
        "qualification_mode": "premerge_subset",
    }
    for field, expected in bindings.items():
        if sidecar[field] != expected:
            raise AuthoritativeRunnerError(
                f"qualification sidecar field {field!r} drifted"
            )
    expected_report_path = (
        output_root
        / str(descriptor["report_path"]).rsplit("/", 1)[0]
        / QUALIFICATION_REPORT_FILENAME
    )
    try:
        actual_report_path = Path(
            str(sidecar["qualification_report_path"])
        ).resolve(strict=True)
    except OSError as exc:
        raise AuthoritativeRunnerError(
            "qualification canonical report is missing"
        ) from exc
    if actual_report_path != expected_report_path:
        raise AuthoritativeRunnerError(
            "qualification report path drifted from the plan"
        )
    verifier = (
        _verify_qualification_report_subprocess
        if report_verifier is None
        else report_verifier
    )
    try:
        verification = verifier(actual_report_path, repo_root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise AuthoritativeRunnerError(
            f"qualification report verification failed: {exc}"
        ) from exc
    if (
        verification.get("payload_digest")
        != sidecar["qualification_report_digest"]
        or verification.get("admission_eligible") is not False
        or verification.get("valid") is not True
    ):
        raise AuthoritativeRunnerError(
            "qualification report digest or authority boundary drifted"
        )

    expected_snapshots = {
        "harness_collection": plan["collections"][
            "qualification_harness"
        ],
        "scenario_collection": plan["collections"][
            "qualification_scenarios"
        ],
    }
    expected_markers: dict[str, tuple[str, ...]] = {}
    expected_node_groups: dict[str, tuple[str, ...]] = {}
    for field, snapshot in expected_snapshots.items():
        expected_nodes = tuple(snapshot["nodes"])
        expected_node_groups[field] = expected_nodes
        marker_map = {
            item["node_id"]: tuple(item["markers"])
            for item in snapshot["markers"]
        }
        expected_markers.update(marker_map)
        raw_collection = sidecar[field]
        if not isinstance(raw_collection, list):
            raise AuthoritativeRunnerError(
                f"qualification {field} is not an array"
            )
        actual_collection: list[dict[str, object]] = []
        for index, raw in enumerate(raw_collection):
            record = _strict_mapping(
                raw,
                fields={"markers", "node_id"},
                context=f"qualification {field}[{index}]",
            )
            node_id = record["node_id"]
            markers = record["markers"]
            if (
                not isinstance(node_id, str)
                or not isinstance(markers, list)
                or any(not isinstance(item, str) for item in markers)
                or markers != sorted(set(markers))
            ):
                raise AuthoritativeRunnerError(
                    f"qualification {field}[{index}] is invalid"
                )
            actual_collection.append(dict(record))
        if [item["node_id"] for item in actual_collection] != list(
            expected_nodes
        ):
            raise AuthoritativeRunnerError(
                f"qualification {field} node set drifted"
            )
        if any(
            tuple(item["markers"]) != expected_markers[item["node_id"]]
            for item in actual_collection
        ):
            raise AuthoritativeRunnerError(
                f"qualification {field} marker set drifted"
            )

    raw_results = sidecar["node_results"]
    if not isinstance(raw_results, list):
        raise AuthoritativeRunnerError(
            "qualification sidecar node results are missing"
        )
    expected_nodes = tuple(
        sorted(
            set(expected_node_groups["harness_collection"])
            | set(expected_node_groups["scenario_collection"])
        )
    )
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_results):
        record = _strict_mapping(
            raw,
            fields=_QUALIFICATION_NODE_FIELDS,
            context=f"qualification node_results[{index}]",
        )
        node_id = record["node_id"]
        outcome = record["outcome"]
        duration_ns = record["duration_ns"]
        markers = record["markers"]
        phases = record["phases"]
        if (
            not isinstance(node_id, str)
            or not isinstance(outcome, str)
            or type(duration_ns) is not int
            or duration_ns < 0
            or not isinstance(markers, list)
            or tuple(markers) != expected_markers.get(node_id)
            or not isinstance(phases, list)
        ):
            raise AuthoritativeRunnerError(
                f"qualification node result {index} is invalid"
            )
        if outcome != "pass":
            raise AuthoritativeRunnerError(
                f"qualification node {node_id!r} is not proven: {outcome}"
            )
        normalized.append(
            {
                "node_id": node_id,
                "owner": "architecture_qualification_premerge",
                "outcome": outcome,
                "duration_ns": duration_ns,
            }
        )
    normalized.sort(key=lambda item: item["node_id"])
    if tuple(item["node_id"] for item in normalized) != expected_nodes:
        raise AuthoritativeRunnerError(
            "qualification sidecar did not prove every Qh/Qs node exactly once"
        )
    qualification_receipt = {
        "status": "verified",
        "sidecar_path": actual_sidecar_path.name,
        "sidecar_digest": sidecar["self_digest"],
        "report_digest": sidecar["qualification_report_digest"],
        "harness_nodes": list(
            expected_node_groups["harness_collection"]
        ),
        "scenario_nodes": list(
            expected_node_groups["scenario_collection"]
        ),
        "node_results_digest": sha256_digest(
            canonical_json_bytes(normalized)
        ),
    }
    return normalized, qualification_receipt


def build_authoritative_receipt(
    *,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    receipt_stages: Sequence[Mapping[str, Any]],
    node_results: Sequence[Mapping[str, Any]],
    unexpected_deselected: Sequence[str],
    frontend_outcomes: Mapping[str, str],
    qualification: Mapping[str, Any],
    total_duration_ns: int,
    general_recheck_observation_digest: str | None,
    general_execution_observation_digest: str | None,
) -> dict[str, Any]:
    """Build one candidate receipt; pure verification remains mandatory."""

    normalized_results = _normalize_node_results(node_results)
    executed_nodes = tuple(
        str(item["node_id"]) for item in normalized_results
    )
    unexpected = tuple(sorted(set(unexpected_deselected)))
    if unexpected != tuple(unexpected_deselected):
        raise AuthoritativeRunnerError(
            "unexpected deselections must be sorted and unique"
        )
    collections = plan["collections"]
    general_nodes = tuple(collections["general"]["nodes"])
    all_stages_pass = all(
        item.get("status") == "ran" and item.get("outcome") == "pass"
        for item in receipt_stages
    )
    ownership = {
        item["node_id"]: item["owner"] for item in plan["node_ownership"]
    }
    node_outcomes_green = all(
        (
            item["outcome"] == "pass"
            if item["owner"] == "architecture_qualification_premerge"
            else item["outcome"] in _GENERAL_PASS_OUTCOMES
        )
        for item in normalized_results
    )
    terminal_status = (
        "pass"
        if (
            all_stages_pass
            and executed_nodes == general_nodes
            and not unexpected
            and node_outcomes_green
            and qualification.get("status") == "verified"
            and all(
                frontend_outcomes.get(stage_id) == "pass"
                for stage_id in ("web_ui_test", "web_ui_build")
            )
        )
        else "fail"
    )
    authority = plan["authority"]
    return seal_document(
        RECEIPT_SCHEMA_ID,
        {
            "invocation_id": plan["invocation_id"],
            "profile_id": "mainline_authoritative",
            "authoritative": authority["authoritative"],
            "admission_eligible": False,
            "live_eligible": False,
            "plan_digest": plan["self_digest"],
            "source_identity_digest": sha256_digest(
                canonical_json_bytes(plan["source_identity"])
            ),
            "stages": [dict(item) for item in receipt_stages],
            "terminal_status": terminal_status,
            "coverage": {
                "collected_nodes": list(general_nodes),
                "owned_nodes_digest": sha256_digest(
                    canonical_json_bytes(
                        [
                            {"node_id": node_id, "owner": ownership[node_id]}
                            for node_id in general_nodes
                        ]
                    )
                ),
                "executed_nodes": list(executed_nodes),
                "node_results": normalized_results,
                "unexpected_deselected": list(unexpected),
                "collection_digest": collections["general"][
                    "collection_digest"
                ],
                "general_recheck_observation_digest": (
                    general_recheck_observation_digest
                ),
                "general_execution_observation_digest": (
                    general_execution_observation_digest
                ),
                "manifest_digest": manifest["self_digest"],
            },
            "frontend": {
                "required_stage_ids": ["web_ui_test", "web_ui_build"],
                "outcomes": dict(frontend_outcomes),
            },
            "qualification": dict(qualification),
            "resource_assignments": {
                "mode": plan["worker_policy"]["mode"],
                "workers": plan["worker_policy"]["workers"],
                "hard_max": plan["worker_policy"]["hard_max"],
                "assignments_digest": sha256_digest(
                    canonical_json_bytes(plan["node_ownership"])
                ),
            },
            "timing": {
                "total_duration_ns": total_duration_ns,
                "stage_duration_ns": {
                    str(item["stage_id"]): int(item["duration_ns"])
                    for item in receipt_stages
                },
            },
        },
    )


def _verify_stage_documents(
    *,
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    stage_documents: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, dict[str, str]]:
    plan_stages = plan["stages"]
    receipt_stages = receipt["stages"]
    if not isinstance(plan_stages, list) or not isinstance(receipt_stages, list):
        raise AuthoritativeRunnerError("stage closure is missing")
    if len(plan_stages) != len(receipt_stages):
        raise AuthoritativeRunnerError("receipt stage count drifted")
    blocked = False
    all_pass = True
    outcomes: dict[str, str] = {}
    for index, (plan_stage, raw_receipt) in enumerate(
        zip(plan_stages, receipt_stages, strict=True)
    ):
        record = _strict_mapping(
            raw_receipt,
            fields=_STAGE_RECEIPT_FIELDS,
            context=f"receipt.stages[{index}]",
        )
        stage_id = plan_stage["stage_id"]
        if record["stage_id"] != stage_id:
            raise AuthoritativeRunnerError("receipt stage order drifted")
        if blocked:
            if dict(record) != _not_run_stage_record(str(stage_id)):
                raise AuthoritativeRunnerError(
                    f"dependent stage {stage_id} ran after failure"
                )
            outcomes[str(stage_id)] = "not_run"
            all_pass = False
            continue
        if record["status"] != "ran":
            raise AuthoritativeRunnerError(
                f"stage {stage_id} is missing its required result"
            )
        result_path = record["result_path"]
        if not isinstance(result_path, str):
            raise AuthoritativeRunnerError(
                f"stage {stage_id} result path is missing"
            )
        pure = PurePosixPath(result_path)
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
            raise AuthoritativeRunnerError(
                f"stage {stage_id} result path is unsafe"
            )
        document = stage_documents.get(str(stage_id))
        if document is None:
            raise AuthoritativeRunnerError(
                f"stage {stage_id} output document is missing"
            )
        try:
            verify_sealed_document(document)
        except ValueError as exc:
            raise AuthoritativeRunnerError(
                f"stage {stage_id} document is invalid: {exc}"
            ) from exc
        if document.get("schema_id") != STAGE_RESULT_SCHEMA_ID:
            raise AuthoritativeRunnerError(
                f"stage {stage_id} result schema is invalid"
            )
        expected_binding = {
            "invocation_id": receipt["invocation_id"],
            "plan_digest": plan["self_digest"],
            "stage_id": stage_id,
            "argv": plan_stage["argv"],
            "cwd": plan_stage["cwd"],
            "environment_digest": plan_stage["environment_digest"],
        }
        for field, value in expected_binding.items():
            if document.get(field) != value:
                raise AuthoritativeRunnerError(
                    f"stage {stage_id} field {field!r} drifted"
                )
        outcome = document.get("outcome")
        if outcome not in _STAGE_OUTCOMES:
            raise AuthoritativeRunnerError(
                f"stage {stage_id} outcome is invalid"
            )
        if (
            record["result_digest"] != document["self_digest"]
            or record["outcome"] != outcome
            or record["duration_ns"] != document.get("duration_ns")
        ):
            raise AuthoritativeRunnerError(
                f"stage {stage_id} receipt binding drifted"
            )
        for stream in ("stdout_tail", "stderr_tail"):
            value = document.get(stream)
            if not isinstance(value, str) or len(value.encode("utf-8")) > 65536:
                raise AuthoritativeRunnerError(
                    f"stage {stage_id} {stream} is not bounded"
                )
        outcomes[str(stage_id)] = str(outcome)
        if outcome != "pass":
            blocked = True
            all_pass = False
    if set(stage_documents) != {
        str(record["stage_id"])
        for record in receipt_stages
        if record["status"] == "ran"
    }:
        raise AuthoritativeRunnerError(
            "stage document set contains missing or unexplained results"
        )
    return all_pass, outcomes


def verify_authoritative_receipt_documents(
    *,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    stage_documents: Mapping[str, Mapping[str, Any]],
    repo_root: Path,
    config: TestGateConfig,
    current_source_identity_digest: str | None = None,
    expected_authoritative: bool = False,
) -> None:
    """Purely recompute one mainline candidate receipt from sealed evidence."""

    try:
        verify_sealed_document(receipt)
    except ValueError as exc:
        raise AuthoritativeRunnerError(
            f"authoritative receipt is invalid: {exc}"
        ) from exc
    try:
        verify_authoritative_plan(
            plan,
            repo_root=repo_root,
            config=config,
            current_source_identity_digest=current_source_identity_digest,
            expected_authoritative=expected_authoritative,
        )
        verify_node_manifest(manifest, plan=plan)
    except AuthoritativePlanError as exc:
        raise AuthoritativeRunnerError(
            f"authoritative plan closure failed: {exc}"
        ) from exc
    if receipt.get("schema_id") != RECEIPT_SCHEMA_ID:
        raise AuthoritativeRunnerError("authoritative receipt schema is invalid")
    if (
        receipt.get("invocation_id") != plan.get("invocation_id")
        or receipt.get("profile_id") != "mainline_authoritative"
        or receipt.get("plan_digest") != plan.get("self_digest")
    ):
        raise AuthoritativeRunnerError(
            "authoritative receipt plan or invocation binding drifted"
        )
    source_digest = sha256_digest(
        canonical_json_bytes(plan["source_identity"])
    )
    if receipt.get("source_identity_digest") != source_digest:
        raise AuthoritativeRunnerError(
            "authoritative receipt source binding drifted"
        )
    if (
        receipt.get("authoritative") is not plan["authority"]["authoritative"]
        or receipt.get("admission_eligible") is not False
        or receipt.get("live_eligible") is not False
    ):
        raise AuthoritativeRunnerError(
            "authoritative receipt authority flags drifted"
        )
    all_stages_pass, stage_outcomes = _verify_stage_documents(
        plan=plan,
        receipt=receipt,
        stage_documents=stage_documents,
    )

    coverage = _strict_mapping(
        receipt.get("coverage"),
        fields=_COVERAGE_FIELDS,
        context="receipt.coverage",
    )
    general_nodes = tuple(plan["collections"]["general"]["nodes"])
    if tuple(coverage["collected_nodes"]) != general_nodes:
        raise AuthoritativeRunnerError("receipt collected-node closure drifted")
    if coverage["collection_digest"] != plan["collections"]["general"][
        "collection_digest"
    ]:
        raise AuthoritativeRunnerError("receipt collection digest drifted")
    if coverage["manifest_digest"] != manifest["self_digest"]:
        raise AuthoritativeRunnerError("receipt manifest binding drifted")
    for field in (
        "general_recheck_observation_digest",
        "general_execution_observation_digest",
    ):
        value = coverage[field]
        if value is not None and (
            not isinstance(value, str) or not value.startswith("sha256:")
        ):
            raise AuthoritativeRunnerError(
                f"receipt {field} is invalid"
            )
    expected_owned_digest = sha256_digest(
        canonical_json_bytes(
            [
                {"node_id": item["node_id"], "owner": item["owner"]}
                for item in plan["node_ownership"]
            ]
        )
    )
    if coverage["owned_nodes_digest"] != expected_owned_digest:
        raise AuthoritativeRunnerError("receipt owner closure drifted")
    unexpected = _sorted_unique_strings(
        coverage["unexpected_deselected"],
        context="receipt.coverage.unexpected_deselected",
    )
    if unexpected:
        raise AuthoritativeRunnerError(
            "receipt contains an unexpected deselection"
        )
    raw_results = coverage["node_results"]
    if not isinstance(raw_results, list):
        raise AuthoritativeRunnerError("receipt node results are missing")
    node_results = _normalize_node_results(raw_results)
    if node_results != raw_results:
        raise AuthoritativeRunnerError(
            "receipt node results are not canonically ordered"
        )
    executed_nodes = _sorted_unique_strings(
        coverage["executed_nodes"],
        context="receipt.coverage.executed_nodes",
    )
    if executed_nodes != tuple(item["node_id"] for item in node_results):
        raise AuthoritativeRunnerError(
            "receipt executed-node and result sets differ"
        )
    expected_owners = {
        item["node_id"]: item["owner"] for item in plan["node_ownership"]
    }
    for result in node_results:
        if expected_owners.get(result["node_id"]) != result["owner"]:
            raise AuthoritativeRunnerError(
                f"receipt node {result['node_id']!r} owner drifted"
            )

    qualification = _strict_mapping(
        receipt.get("qualification"),
        fields=_QUALIFICATION_FIELDS,
        context="receipt.qualification",
    )
    harness_nodes = tuple(plan["collections"]["qualification_harness"]["nodes"])
    scenario_nodes = tuple(
        plan["collections"]["qualification_scenarios"]["nodes"]
    )
    qualification_nodes = tuple(
        sorted(set(harness_nodes) | set(scenario_nodes))
    )
    qualification_results = [
        item
        for item in node_results
        if item["owner"] == "architecture_qualification_premerge"
    ]
    general_results = [
        item
        for item in node_results
        if item["owner"] == "general_non_live_pytest"
    ]
    if qualification["status"] == "verified":
        sidecar_path = qualification["sidecar_path"]
        if not isinstance(sidecar_path, str):
            raise AuthoritativeRunnerError(
                "verified qualification sidecar path is missing"
            )
        pure = PurePosixPath(sidecar_path)
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
            raise AuthoritativeRunnerError(
                "qualification sidecar path is unsafe"
            )
        if (
            tuple(qualification["harness_nodes"]) != harness_nodes
            or tuple(qualification["scenario_nodes"]) != scenario_nodes
            or tuple(item["node_id"] for item in qualification_results)
            != qualification_nodes
            or qualification["node_results_digest"]
            != sha256_digest(canonical_json_bytes(qualification_results))
            or not isinstance(qualification["sidecar_digest"], str)
            or not isinstance(qualification["report_digest"], str)
        ):
            raise AuthoritativeRunnerError(
                "qualification receipt closure drifted"
            )
    elif qualification["status"] == "not_run":
        if dict(qualification) != {
            "status": "not_run",
            "sidecar_path": None,
            "sidecar_digest": None,
            "report_digest": None,
            "harness_nodes": [],
            "scenario_nodes": [],
            "node_results_digest": sha256_digest(canonical_json_bytes([])),
        }:
            raise AuthoritativeRunnerError(
                "not-run qualification evidence is malformed"
            )
    else:
        raise AuthoritativeRunnerError("qualification status is invalid")

    frontend = _strict_mapping(
        receipt.get("frontend"),
        fields=_FRONTEND_FIELDS,
        context="receipt.frontend",
    )
    if frontend["required_stage_ids"] != ["web_ui_test", "web_ui_build"]:
        raise AuthoritativeRunnerError("mandatory frontend stages drifted")
    if not isinstance(frontend["outcomes"], dict) or set(
        frontend["outcomes"]
    ) != {"web_ui_test", "web_ui_build"}:
        raise AuthoritativeRunnerError("frontend outcomes are incomplete")
    for stage_id in ("web_ui_test", "web_ui_build"):
        if frontend["outcomes"][stage_id] != stage_outcomes[stage_id]:
            raise AuthoritativeRunnerError(
                f"frontend outcome drifted for {stage_id}"
            )

    resource = _strict_mapping(
        receipt.get("resource_assignments"),
        fields=_RESOURCE_FIELDS,
        context="receipt.resource_assignments",
    )
    if dict(resource) != {
        "mode": plan["worker_policy"]["mode"],
        "workers": plan["worker_policy"]["workers"],
        "hard_max": plan["worker_policy"]["hard_max"],
        "assignments_digest": sha256_digest(
            canonical_json_bytes(plan["node_ownership"])
        ),
    }:
        raise AuthoritativeRunnerError("receipt resource assignment drifted")
    timing = _strict_mapping(
        receipt.get("timing"),
        fields=_TIMING_FIELDS,
        context="receipt.timing",
    )
    if type(timing["total_duration_ns"]) is not int or timing[
        "total_duration_ns"
    ] < 0:
        raise AuthoritativeRunnerError("receipt total timing is invalid")
    expected_stage_timing = {
        str(item["stage_id"]): int(item["duration_ns"])
        for item in receipt["stages"]
    }
    if timing["stage_duration_ns"] != expected_stage_timing:
        raise AuthoritativeRunnerError("receipt stage timing drifted")

    node_outcomes_green = all(
        (
            item["outcome"] == "pass"
            if item["owner"] == "architecture_qualification_premerge"
            else item["outcome"] in _GENERAL_PASS_OUTCOMES
        )
        for item in node_results
    )
    expected_terminal = (
        "pass"
        if (
            all_stages_pass
            and executed_nodes == general_nodes
            and qualification["status"] == "verified"
            and len(qualification_results) == len(qualification_nodes)
            and len(general_results)
            == len(general_nodes) - len(qualification_nodes)
            and node_outcomes_green
            and all(
                frontend["outcomes"][stage_id] == "pass"
                for stage_id in ("web_ui_test", "web_ui_build")
            )
        )
        else "fail"
    )
    if receipt.get("terminal_status") != expected_terminal:
        raise AuthoritativeRunnerError(
            "authoritative receipt terminal status drifted"
        )
    if expected_terminal == "pass" and (
        coverage["general_recheck_observation_digest"] is None
        or coverage["general_execution_observation_digest"] is None
    ):
        raise AuthoritativeRunnerError(
            "passing receipt lacks general collection/execution evidence"
        )


def _verify_authoritative_output(
    *,
    output_root: Path,
    repo_root: Path,
    config: TestGateConfig,
    current_source_identity_digest: str | None = None,
    expected_authoritative: bool,
    plan_filename: str,
    receipt_filename: str,
) -> MainlineCandidateVerificationResult:
    """Reload every required artifact in one authority domain."""

    root = repo_root.resolve(strict=True)
    evidence_root = _candidate_output_root(
        output_root=output_root,
        repo_root=root,
    )
    plan = _load_candidate_document(
        evidence_root / plan_filename,
        context="candidate execution plan",
    )
    manifest = _load_candidate_document(
        evidence_root / NODE_MANIFEST_FILENAME,
        context="candidate residual manifest",
    )
    receipt = _load_candidate_document(
        evidence_root / receipt_filename,
        context="candidate receipt",
    )
    if plan.get("output_root") != str(evidence_root):
        raise AuthoritativeRunnerError(
            "candidate plan output root drifted from the evidence bundle"
        )

    raw_stage_records = receipt.get("stages")
    if not isinstance(raw_stage_records, list):
        raise AuthoritativeRunnerError("candidate receipt stages are missing")
    stage_documents: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(raw_stage_records):
        if not isinstance(raw, dict):
            raise AuthoritativeRunnerError(
                f"candidate receipt stage {index} is malformed"
            )
        if raw.get("status") != "ran":
            continue
        stage_id = raw.get("stage_id")
        result_path = raw.get("result_path")
        if not isinstance(stage_id, str) or not isinstance(result_path, str):
            raise AuthoritativeRunnerError(
                f"candidate receipt stage {index} path is malformed"
            )
        pure_path = PurePosixPath(result_path)
        if (
            pure_path.is_absolute()
            or ".." in pure_path.parts
            or len(pure_path.parts) != 1
        ):
            raise AuthoritativeRunnerError(
                f"candidate receipt stage {stage_id} path is unsafe"
            )
        if stage_id in stage_documents:
            raise AuthoritativeRunnerError(
                f"candidate receipt stage {stage_id} is duplicated"
            )
        stage_documents[stage_id] = _load_candidate_document(
            evidence_root / result_path,
            context=f"candidate stage {stage_id}",
        )

    source_digest = (
        collect_source_identity(root).digest
        if current_source_identity_digest is None
        else current_source_identity_digest
    )
    verify_authoritative_receipt_documents(
        plan=plan,
        manifest=manifest,
        receipt=receipt,
        stage_documents=stage_documents,
        repo_root=root,
        config=config,
        current_source_identity_digest=source_digest,
        expected_authoritative=expected_authoritative,
    )

    coverage = receipt["coverage"]
    recheck_digest = coverage["general_recheck_observation_digest"]
    if recheck_digest is not None:
        actual_recheck_digest = load_and_verify_general_recheck(
            plan=plan,
            observation_path=(
                evidence_root / GENERAL_RECHECK_OBSERVATION_FILENAME
            ),
        )
        if actual_recheck_digest != recheck_digest:
            raise AuthoritativeRunnerError(
                "candidate general recheck digest drifted"
            )

    raw_node_results: list[dict[str, Any]] = []
    general_digest = coverage["general_execution_observation_digest"]
    if general_digest is not None:
        general_results, actual_general_digest = (
            load_and_verify_general_execution(
                plan=plan,
                manifest=manifest,
                observation_path=(
                    evidence_root / GENERAL_EXECUTION_OBSERVATION_FILENAME
                ),
            )
        )
        if actual_general_digest != general_digest:
            raise AuthoritativeRunnerError(
                "candidate general execution digest drifted"
            )
        resource_path = plan["collections"]["resource_manifest"]["path"]
        try:
            partition_closure = verify_general_partition_bundle(
                repo_root=root,
                output_root=evidence_root,
                plan=plan,
                general_manifest=manifest,
                resource_manifest_path=root / str(resource_path),
                config=config,
                require_worker_paths=False,
            )
        except (GeneralPartitionError, KeyError, TypeError) as exc:
            raise AuthoritativeRunnerError(
                f"candidate partition evidence closure failed: {exc}"
            ) from exc
        if partition_closure["merged_observation_digest"] != general_digest:
            raise AuthoritativeRunnerError(
                "candidate partition bundle and receipt digest differ"
            )
        raw_node_results.extend(general_results)

    qualification = receipt["qualification"]
    if qualification["status"] == "verified":
        qualification_results, qualification_receipt = (
            load_and_verify_qualification_sidecar(
                plan=plan,
                sidecar_path=evidence_root / QUALIFICATION_SIDECAR_FILENAME,
                repo_root=root,
            )
        )
        if qualification_receipt != qualification:
            raise AuthoritativeRunnerError(
                "candidate qualification receipt drifted from its sidecar"
            )
        raw_node_results.extend(qualification_results)

    recomputed_results = _normalize_node_results(raw_node_results)
    if recomputed_results != coverage["node_results"]:
        raise AuthoritativeRunnerError(
            "candidate raw evidence and receipt node results differ"
        )
    if [item["node_id"] for item in recomputed_results] != coverage[
        "executed_nodes"
    ]:
        raise AuthoritativeRunnerError(
            "candidate raw evidence and executed-node closure differ"
        )
    return MainlineCandidateVerificationResult(
        output_root=evidence_root,
        plan=plan,
        manifest=manifest,
        receipt=receipt,
    )


def verify_authoritative_candidate_output(
    *,
    output_root: Path,
    repo_root: Path,
    config: TestGateConfig,
    current_source_identity_digest: str | None = None,
) -> MainlineCandidateVerificationResult:
    """Reload and verify a complete non-authoritative candidate bundle."""

    return _verify_authoritative_output(
        output_root=output_root,
        repo_root=repo_root,
        config=config,
        current_source_identity_digest=current_source_identity_digest,
        expected_authoritative=False,
        plan_filename=PLAN_FILENAME,
        receipt_filename=MAINLINE_CANDIDATE_RECEIPT_FILENAME,
    )


def verify_authoritative_mainline_output(
    *,
    output_root: Path,
    repo_root: Path,
    config: TestGateConfig,
    current_source_identity_digest: str | None = None,
) -> MainlineCandidateVerificationResult:
    """Reload and verify a complete merge-authoritative non-live bundle."""

    return _verify_authoritative_output(
        output_root=output_root,
        repo_root=repo_root,
        config=config,
        current_source_identity_digest=current_source_identity_digest,
        expected_authoritative=True,
        plan_filename=MAINLINE_AUTHORITATIVE_PLAN_FILENAME,
        receipt_filename=MAINLINE_AUTHORITATIVE_RECEIPT_FILENAME,
    )


def _not_run_qualification_receipt() -> dict[str, Any]:
    return {
        "status": "not_run",
        "sidecar_path": None,
        "sidecar_digest": None,
        "report_digest": None,
        "harness_nodes": [],
        "scenario_nodes": [],
        "node_results_digest": sha256_digest(canonical_json_bytes([])),
    }


def _execute_authoritative_plan(
    *,
    plan_result: AuthoritativePlanResult,
    repo_root: Path,
    config: TestGateConfig,
    environments: Mapping[str, Mapping[str, str]],
    process_runner: Callable[..., ProcessResult] = run_command,
    source_collector: Callable[[Path], SourceIdentity] = collect_source_identity,
    expected_authoritative: bool,
    receipt_filename: str,
) -> MainlineCandidateRunResult:
    """Execute one optimized plan in its explicitly selected authority mode."""

    started = time.monotonic_ns()
    root = repo_root.resolve(strict=True)
    plan = plan_result.plan
    manifest = plan_result.manifest
    output_root = plan_result.output_root
    expected_source_digest = sha256_digest(
        canonical_json_bytes(plan["source_identity"])
    )
    recheck_digest: str | None = None
    execution_digest: str | None = None
    qualification_results: list[dict[str, Any]] = []
    general_results: list[dict[str, Any]] = []
    qualification_receipt = _not_run_qualification_receipt()

    def assert_source_stable(context: str) -> None:
        if source_collector(root).digest != expected_source_digest:
            raise AuthoritativeRunnerError(
                f"source identity drifted {context}"
            )

    def before_stage(stage_id: str) -> None:
        nonlocal recheck_digest
        nonlocal execution_digest
        nonlocal qualification_results
        nonlocal general_results
        nonlocal qualification_receipt
        if stage_id == "architecture_qualification_premerge":
            recheck = plan["collections"]["general_recheck"]
            result = process_runner(
                tuple(recheck["argv"]),
                cwd=Path(str(recheck["cwd"])),
                environment=environments["general_non_live_pytest"],
                timeout_seconds=float(recheck["deadline_seconds"]),
            )
            stage = {
                "stage_id": "general_collection_recheck",
                "environment_digest": recheck["environment_digest"],
            }
            document = _stage_result_document(
                invocation_id=str(plan["invocation_id"]),
                plan_digest=str(plan["self_digest"]),
                stage=stage,
                result=result,
            )
            publish_no_replace(
                output_root / str(recheck["stage_result_path"]),
                canonical_document_bytes(document),
            )
            if result.outcome != "pass":
                raise AuthoritativeRunnerError(
                    "same-invocation G recollection failed before qualification"
                )
            recheck_digest = load_and_verify_general_recheck(
                plan=plan,
                observation_path=(
                    output_root / GENERAL_RECHECK_OBSERVATION_FILENAME
                ),
            )
            assert_source_stable("after general recollection")
        elif stage_id == "general_non_live_pytest":
            (
                qualification_results,
                qualification_receipt,
            ) = load_and_verify_qualification_sidecar(
                plan=plan,
                sidecar_path=output_root / QUALIFICATION_SIDECAR_FILENAME,
                repo_root=root,
            )
            assert_source_stable("after qualification")
        elif stage_id == "web_ui_test":
            general_results, execution_digest = (
                load_and_verify_general_execution(
                    plan=plan,
                    manifest=manifest,
                    observation_path=(
                        output_root / "general-residual-observation.json"
                    ),
                )
            )
            assert_source_stable("after general residual execution")

    def transform_environment(
        stage_id: str,
        environment: Mapping[str, str],
    ) -> Mapping[str, str]:
        if stage_id != "architecture_qualification_premerge":
            return environment
        bound = dict(environment)
        qualification_stage = next(
            stage
            for stage in plan["stages"]
            if stage["stage_id"] == stage_id
        )
        bound.update(
            {
                _MAINLINE_SIDECAR_OUTPUT_ENV: str(
                    output_root / QUALIFICATION_SIDECAR_FILENAME
                ),
                _MAINLINE_INVOCATION_ID_ENV: str(plan["invocation_id"]),
                _MAINLINE_PLAN_DIGEST_ENV: str(plan["self_digest"]),
                _MAINLINE_SOURCE_DIGEST_ENV: expected_source_digest,
                _MAINLINE_ENVIRONMENT_DIGEST_ENV: str(
                    qualification_stage["environment_digest"]
                ),
            }
        )
        return bound

    sequence = run_fail_fast_stage_sequence(
        plan=plan,
        manifest=manifest,
        repo_root=root,
        config=config,
        environments=environments,
        process_runner=process_runner,
        source_collector=source_collector,
        before_stage=before_stage,
        environment_transform=transform_environment,
        expected_authoritative=expected_authoritative,
    )
    if (
        sequence.first_failing_stage is None
        and not general_results
    ):
        general_results, execution_digest = load_and_verify_general_execution(
            plan=plan,
            manifest=manifest,
            observation_path=output_root
            / "general-residual-observation.json",
        )
    if (
        sequence.first_failing_stage is None
        and not qualification_results
    ):
        (
            qualification_results,
            qualification_receipt,
        ) = load_and_verify_qualification_sidecar(
            plan=plan,
            sidecar_path=output_root / QUALIFICATION_SIDECAR_FILENAME,
            repo_root=root,
        )
    stage_outcomes = {
        str(item["stage_id"]): str(item["outcome"])
        for item in sequence.receipt_stages
    }
    receipt = build_authoritative_receipt(
        plan=plan,
        manifest=manifest,
        receipt_stages=sequence.receipt_stages,
        node_results=[*qualification_results, *general_results],
        unexpected_deselected=(),
        frontend_outcomes={
            "web_ui_test": stage_outcomes["web_ui_test"],
            "web_ui_build": stage_outcomes["web_ui_build"],
        },
        qualification=qualification_receipt,
        total_duration_ns=max(0, time.monotonic_ns() - started),
        general_recheck_observation_digest=recheck_digest,
        general_execution_observation_digest=execution_digest,
    )
    assert_source_stable("before receipt publication")
    verify_authoritative_receipt_documents(
        plan=plan,
        manifest=manifest,
        receipt=receipt,
        stage_documents=sequence.stage_documents,
        repo_root=root,
        config=config,
        current_source_identity_digest=expected_source_digest,
        expected_authoritative=expected_authoritative,
    )
    publish_no_replace(
        output_root / receipt_filename,
        canonical_document_bytes(receipt),
    )
    return MainlineCandidateRunResult(
        output_root=output_root,
        plan=plan,
        manifest=manifest,
        receipt=receipt,
        terminal_status=str(receipt["terminal_status"]),
    )


def execute_authoritative_shadow_candidate(
    *,
    plan_result: AuthoritativePlanResult,
    repo_root: Path,
    config: TestGateConfig,
    environments: Mapping[str, Mapping[str, str]],
    process_runner: Callable[..., ProcessResult] = run_command,
    source_collector: Callable[[Path], SourceIdentity] = collect_source_identity,
) -> MainlineCandidateRunResult:
    """Execute one optimized candidate while merge authority stays elsewhere."""

    return _execute_authoritative_plan(
        plan_result=plan_result,
        repo_root=repo_root,
        config=config,
        environments=environments,
        process_runner=process_runner,
        source_collector=source_collector,
        expected_authoritative=False,
        receipt_filename=MAINLINE_CANDIDATE_RECEIPT_FILENAME,
    )


def execute_authoritative_mainline(
    *,
    plan_result: AuthoritativePlanResult,
    repo_root: Path,
    config: TestGateConfig,
    environments: Mapping[str, Mapping[str, str]],
    process_runner: Callable[..., ProcessResult] = run_command,
    source_collector: Callable[[Path], SourceIdentity] = collect_source_identity,
) -> MainlineCandidateRunResult:
    """Execute one explicit merge-authoritative non-live mainline plan."""

    return _execute_authoritative_plan(
        plan_result=plan_result,
        repo_root=repo_root,
        config=config,
        environments=environments,
        process_runner=process_runner,
        source_collector=source_collector,
        expected_authoritative=True,
        receipt_filename=MAINLINE_AUTHORITATIVE_RECEIPT_FILENAME,
    )


def run_authoritative_shadow_candidate(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    ambient_environment: Mapping[str, str] | None = None,
    resource_manifest_path: Path = DEFAULT_RESOURCE_MANIFEST_PATH,
    workers: int = 1,
) -> MainlineCandidateRunResult:
    """Plan and run a full optimized candidate without changing authority."""

    root = repo_root.resolve(strict=True)
    plan_result = run_authoritative_shadow_plan(
        repo_root=root,
        output_root=output_root,
        config=config,
        invocation_id=invocation_id,
        ambient_environment=ambient_environment,
        resource_manifest_path=resource_manifest_path,
        workers=workers,
    )
    environments = stage_environments(
        config=config,
        repo_root=root,
        source=ambient_environment,
    )
    return execute_authoritative_shadow_candidate(
        plan_result=plan_result,
        repo_root=root,
        config=config,
        environments=environments,
    )


def run_authoritative_mainline(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    ambient_environment: Mapping[str, str] | None = None,
    resource_manifest_path: Path = DEFAULT_RESOURCE_MANIFEST_PATH,
    workers: int = 1,
) -> MainlineCandidateRunResult:
    """Plan and run the complete non-live merge-authoritative mainline."""

    root = repo_root.resolve(strict=True)
    plan_result = run_authoritative_mainline_plan(
        repo_root=root,
        output_root=output_root,
        config=config,
        invocation_id=invocation_id,
        ambient_environment=ambient_environment,
        resource_manifest_path=resource_manifest_path,
        workers=workers,
    )
    environments = stage_environments(
        config=config,
        repo_root=root,
        source=ambient_environment,
    )
    return execute_authoritative_mainline(
        plan_result=plan_result,
        repo_root=root,
        config=config,
        environments=environments,
    )


def monotonic_elapsed_ns(started_monotonic_ns: int) -> int:
    """Return a nonnegative total duration for receipt construction."""

    return max(0, time.monotonic_ns() - started_monotonic_ns)
    load_canonical_document_bytes,
