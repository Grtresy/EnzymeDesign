"""Legacy mainline timing, stage attribution, and paired baseline reduction."""

from __future__ import annotations

import json
import os
import platform
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import TestGateConfig
from .model import (
    BENCHMARK_SUMMARY_SCHEMA_ID,
    LEGACY_SAMPLE_SCHEMA_ID,
    LEGACY_STAGE_ATTRIBUTION_SCHEMA_ID,
    PHASE0_BASELINE_SCHEMA_ID,
    PYTEST_OBSERVATION_BINDING_SCHEMA_ID,
    PYTEST_OBSERVATION_SCHEMA_ID,
    SHADOW_COVERAGE_SCHEMA_ID,
    STAGE_RESULT_SCHEMA_ID,
    canonical_document_bytes,
    canonical_json_bytes,
    load_canonical_document_bytes,
    seal_document,
    sha256_digest,
)
from .runner import (
    ProcessResult,
    create_new_output_root,
    publish_no_replace,
    run_command,
)
from .source import SourceIdentity, collect_source_identity

QUALIFICATION_REPORT_FILENAME = "architecture-qualification-report.json"
_PYTEST_DURATION = re.compile(r"\bin (?P<seconds>[0-9]+(?:\.[0-9]+)?)s\b")


class BenchmarkError(RuntimeError):
    """Raised when a timing sample or baseline is not source-bound and closed."""


@dataclass(frozen=True)
class LegacySampleResult:
    output_root: Path
    document: Mapping[str, Any]
    functional_green: bool


@dataclass(frozen=True)
class LegacyStageAttributionResult:
    output_root: Path
    document: Mapping[str, Any]
    terminal_status: str


def collect_host_identity() -> dict[str, object]:
    """Collect stable same-boot host fields without current-load noise."""

    boot_id_path = Path("/proc/sys/kernel/random/boot_id")
    try:
        boot_id = boot_id_path.read_text(encoding="ascii").strip()
    except OSError:
        boot_id_digest = "unavailable"
    else:
        boot_id_digest = sha256_digest(boot_id.encode("ascii"))
    memory_bytes: int | None = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                memory_bytes = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError, IndexError):
        memory_bytes = None
    payload: dict[str, object] = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "memory_bytes": memory_bytes,
        "boot_id_digest": boot_id_digest,
    }
    payload["fingerprint"] = sha256_digest(canonical_json_bytes(payload))
    return payload


def _stage_result_document(
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


def _assert_source_recheck(
    before: SourceIdentity,
    after: SourceIdentity,
) -> None:
    if before.digest != after.digest:
        raise BenchmarkError(
            f"source identity drifted during benchmark: "
            f"{before.digest} != {after.digest}"
        )


def run_legacy_sample(
    *,
    repo_root: Path,
    output_root: Path,
    invocation_id: str,
    sample_kind: str,
    sample_index: int,
    timeout_seconds: float = 3600.0,
) -> LegacySampleResult:
    """Time the frozen legacy rollback comparison as one external process."""

    if sample_kind not in {"cold", "warm"}:
        raise BenchmarkError("sample_kind must be cold or warm")
    if type(sample_index) is not int or sample_index < 1:
        raise BenchmarkError("sample_index must be a positive integer")
    root = repo_root.resolve(strict=True)
    evidence_root = create_new_output_root(root, output_root)
    source_before = collect_source_identity(root)
    host_identity = collect_host_identity()
    command = ("./scripts/check-mainline-legacy.sh",)
    process = run_command(
        command,
        cwd=root,
        timeout_seconds=timeout_seconds,
        tail_bytes=256 * 1024,
    )
    source_after = collect_source_identity(root)
    source_drift = source_before.digest != source_after.digest
    functional_green = process.outcome == "pass" and not source_drift
    process_payload = process.as_dict()
    process_payload["source_recheck_digest"] = source_after.digest
    process_payload["source_drift"] = source_drift
    document = seal_document(
        LEGACY_SAMPLE_SCHEMA_ID,
        {
            "invocation_id": invocation_id,
            "sample_kind": sample_kind,
            "sample_index": sample_index,
            "cache_control": "process_only",
            "source_identity": source_before.as_dict(),
            "source_identity_digest": source_before.digest,
            "host_identity": host_identity,
            "command": list(command),
            "process_result": process_payload,
            "functional_green": functional_green,
        },
    )
    publish_no_replace(
        evidence_root / "legacy-sample.json",
        canonical_document_bytes(document),
    )
    return LegacySampleResult(
        output_root=evidence_root,
        document=document,
        functional_green=functional_green,
    )


def _qualification_attribution(report_path: Path) -> dict[str, object]:
    try:
        content = report_path.read_bytes()
        document = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "path": str(report_path),
            "present": False,
            "error": f"{type(exc).__name__}:{exc}",
        }
    payload = document.get("payload") if isinstance(document, dict) else None
    if not isinstance(payload, dict):
        return {
            "path": str(report_path),
            "present": True,
            "document_digest": sha256_digest(content),
            "error": "missing payload",
        }
    harness = payload.get("harness")
    scenarios = payload.get("scenario_results")
    scenario_durations: list[dict[str, object]] = []
    if isinstance(scenarios, list):
        for item in scenarios:
            if isinstance(item, dict):
                scenario_durations.append(
                    {
                        "scenario_id": item.get("scenario_id"),
                        "duration_milliseconds": item.get(
                            "duration_milliseconds"
                        ),
                    }
                )
    return {
        "path": str(report_path),
        "present": True,
        "document_digest": sha256_digest(content),
        "collection_plus_harness_duration_milliseconds": (
            harness.get("duration_milliseconds")
            if isinstance(harness, dict)
            else None
        ),
        "scenario_durations": scenario_durations,
        "scenario_total_milliseconds": sum(
            int(item["duration_milliseconds"])
            for item in scenario_durations
            if type(item["duration_milliseconds"]) is int
        ),
    }


def _reported_pytest_seconds(process: ProcessResult) -> float | None:
    matches = list(_PYTEST_DURATION.finditer(process.stdout.tail))
    if not matches:
        return None
    return float(matches[-1].group("seconds"))


def run_legacy_stage_attribution(
    *,
    repo_root: Path,
    output_root: Path,
    invocation_id: str,
    config: TestGateConfig,
) -> LegacyStageAttributionResult:
    """Run exact legacy stage commands separately for diagnostic attribution."""

    root = repo_root.resolve(strict=True)
    evidence_root = create_new_output_root(root, output_root)
    source_before = collect_source_identity(root)
    plan_digest = sha256_digest(
        canonical_json_bytes(
            {
                "operation": "legacy_stage_attribution",
                "invocation_id": invocation_id,
                "source_identity_digest": source_before.digest,
                "config_digest": config.digest,
            }
        )
    )
    stages: list[dict[str, object]] = []
    first_failing_stage: str | None = None
    qualification_report_root = evidence_root / "qualification-report"
    for stage_id in config.profile("mainline_authoritative").stage_ids:
        stage = config.stage(stage_id)
        argv = tuple(
            str(qualification_report_root)
            if argument == "{qualification_output_root}"
            else argument
            for argument in stage.argv
        )
        stage_cwd = root if stage.cwd == "." else root / stage.cwd
        process = run_command(
            argv,
            cwd=stage_cwd,
            timeout_seconds=float(stage.deadline_seconds),
            tail_bytes=256 * 1024,
        )
        environment_digest = sha256_digest(
            canonical_json_bytes(
                {
                    "policy": stage.environment_policy,
                    "mode": "legacy_ambient_exact_command",
                }
            )
        )
        stage_document = _stage_result_document(
            invocation_id=invocation_id,
            plan_digest=plan_digest,
            stage_id=stage_id,
            environment_digest=environment_digest,
            result=process,
        )
        publish_no_replace(
            evidence_root / f"{stage_id}-stage.json",
            canonical_document_bytes(stage_document),
        )
        stage_summary: dict[str, object] = {
            "stage_id": stage_id,
            "stage_result_digest": stage_document["self_digest"],
            "duration_ns": process.duration_ns,
            "outcome": process.outcome,
        }
        if stage_id == "general_non_live_pytest":
            reported_seconds = _reported_pytest_seconds(process)
            stage_summary["pytest_reported_seconds"] = reported_seconds
            stage_summary["process_overhead_seconds"] = (
                None
                if reported_seconds is None
                else max(0.0, process.duration_ns / 1_000_000_000 - reported_seconds)
            )
        stages.append(stage_summary)
        if process.outcome != "pass":
            first_failing_stage = stage_id
            break

    source_after = collect_source_identity(root)
    source_drift = source_before.digest != source_after.digest
    terminal_status = (
        "pass" if first_failing_stage is None and not source_drift else "fail"
    )
    qualification_report = _qualification_attribution(
        qualification_report_root / QUALIFICATION_REPORT_FILENAME
    )
    fields: dict[str, object] = {
        "invocation_id": invocation_id,
        "source_identity_digest": source_before.digest,
        "stages": stages,
        "terminal_status": terminal_status,
        "qualification_report": qualification_report,
    }
    if first_failing_stage is not None:
        fields["first_failing_stage"] = first_failing_stage
    if source_drift:
        fields["first_failing_stage"] = "source_recheck"
    document = seal_document(LEGACY_STAGE_ATTRIBUTION_SCHEMA_ID, fields)
    publish_no_replace(
        evidence_root / "legacy-stage-attribution.json",
        canonical_document_bytes(document),
    )
    return LegacyStageAttributionResult(
        output_root=evidence_root,
        document=document,
        terminal_status=terminal_status,
    )


def _sample_document(path: Path) -> dict[str, Any]:
    try:
        document = load_canonical_document_bytes(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise BenchmarkError(f"invalid legacy sample {path}: {exc}") from exc
    if document["schema_id"] != LEGACY_SAMPLE_SCHEMA_ID:
        raise BenchmarkError(f"unexpected sample schema in {path}")
    return document


def _duration_ns(document: Mapping[str, Any]) -> int:
    process_result = document.get("process_result")
    if not isinstance(process_result, dict):
        raise BenchmarkError("legacy sample process_result is invalid")
    duration = process_result.get("duration_ns")
    if type(duration) is not int or duration < 0:
        raise BenchmarkError("legacy sample duration_ns is invalid")
    return duration


def _distribution(values: Sequence[int]) -> dict[str, object]:
    if not values:
        raise BenchmarkError("cannot summarize an empty distribution")
    median = statistics.median(values)
    absolute_deviations = [abs(value - median) for value in values]
    return {
        "count": len(values),
        "median_ns": median,
        "mad_ns": statistics.median(absolute_deviations),
        "min_ns": min(values),
        "max_ns": max(values),
    }


def build_legacy_baseline_summary(
    sample_paths: Sequence[Path],
) -> dict[str, Any]:
    """Reduce at least five green same-identity cold/warm pairs."""

    documents = [_sample_document(path) for path in sample_paths]
    by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for document in documents:
        sample_index = document.get("sample_index")
        sample_kind = document.get("sample_kind")
        if type(sample_index) is not int or sample_kind not in {"cold", "warm"}:
            raise BenchmarkError("legacy sample pair identity is invalid")
        key = (sample_index, sample_kind)
        if key in by_key:
            raise BenchmarkError(f"duplicate legacy sample key: {key!r}")
        by_key[key] = document

    valid_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    invalid_samples: list[dict[str, object]] = []
    for sample_index in sorted({key[0] for key in by_key}):
        cold = by_key.get((sample_index, "cold"))
        warm = by_key.get((sample_index, "warm"))
        if cold is None or warm is None:
            invalid_samples.append(
                {"sample_index": sample_index, "reason": "missing_pair_member"}
            )
            continue
        identity_fields = (
            "source_identity_digest",
            "host_identity",
            "command",
            "cache_control",
        )
        if any(cold[field] != warm[field] for field in identity_fields):
            invalid_samples.append(
                {"sample_index": sample_index, "reason": "paired_identity_drift"}
            )
            continue
        if not cold["functional_green"] or not warm["functional_green"]:
            invalid_samples.append(
                {"sample_index": sample_index, "reason": "functional_failure"}
            )
            continue
        valid_pairs.append((cold, warm))
    if len(valid_pairs) < 5:
        raise BenchmarkError(
            f"legacy baseline requires at least five valid pairs; got {len(valid_pairs)}"
        )

    first = valid_pairs[0][0]
    common_source = first["source_identity_digest"]
    common_host = first["host_identity"]
    common_command = first["command"]
    for cold, warm in valid_pairs:
        for document in (cold, warm):
            if (
                document["source_identity_digest"] != common_source
                or document["host_identity"] != common_host
                or document["command"] != common_command
            ):
                raise BenchmarkError(
                    "valid baseline pairs do not share one source, host, and command"
                )
    cold_samples = [
        {
            "invocation_id": cold["invocation_id"],
            "sample_index": cold["sample_index"],
            "duration_ns": _duration_ns(cold),
            "sample_digest": cold["self_digest"],
        }
        for cold, _ in valid_pairs
    ]
    warm_samples = [
        {
            "invocation_id": warm["invocation_id"],
            "sample_index": warm["sample_index"],
            "duration_ns": _duration_ns(warm),
            "sample_digest": warm["self_digest"],
        }
        for _, warm in valid_pairs
    ]
    source_identity = first["source_identity"]
    if not isinstance(source_identity, dict):
        raise BenchmarkError("sample source identity is invalid")
    document = seal_document(
        BENCHMARK_SUMMARY_SCHEMA_ID,
        {
            "source_identity_digest": common_source,
            "host_identity": common_host,
            "toolchain_identity": source_identity.get("toolchains"),
            "cache_control": "process_only",
            "cold_samples": cold_samples,
            "warm_samples": warm_samples,
            "statistics": {
                "valid_pair_count": len(valid_pairs),
                "cold": _distribution(
                    [int(item["duration_ns"]) for item in cold_samples]
                ),
                "warm": _distribution(
                    [int(item["duration_ns"]) for item in warm_samples]
                ),
            },
            "invalid_samples": invalid_samples,
            "stage_breakdown": [],
            "planning_overhead": {
                "legacy_runner": "external_total_only",
                "duration_ns": 0,
            },
        },
    )
    return document


def _load_expected_schema(path: Path, schema_id: str) -> dict[str, Any]:
    try:
        document = load_canonical_document_bytes(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise BenchmarkError(f"invalid evidence {path}: {exc}") from exc
    if document["schema_id"] != schema_id:
        raise BenchmarkError(
            f"unexpected schema in {path}: {document['schema_id']!r}"
        )
    return document


def _shadow_identity(document: Mapping[str, Any]) -> dict[str, object]:
    return {
        "source_identity_digest": document["source_identity_digest"],
        "general_collection_digest": document["general_collection_digest"],
        "qualification_harness_collection_digest": document[
            "qualification_harness_collection_digest"
        ],
        "qualification_scenario_collection_digest": document[
            "qualification_scenario_collection_digest"
        ],
        "legacy_execution_multiset_digest": document[
            "legacy_execution_multiset_digest"
        ],
        "distinct_coverage_digest": document["distinct_coverage_digest"],
        "distinct_required_nodes": document["distinct_required_nodes"],
        "structural_duplicates": document["structural_duplicates"],
        "shadow_owners": document["shadow_owners"],
        "frontend_commands": document.get("frontend_commands"),
    }


def _shadow_collection_overhead_ns(shadow_path: Path) -> int:
    total = 0
    stage_paths = (
        shadow_path.parent / "general_collection-stage.json",
        shadow_path.parent / "qualification_harness_collection-stage.json",
        shadow_path.parent / "qualification_scenario_collection-stage.json",
    )
    for stage_path in stage_paths:
        stage = _load_expected_schema(stage_path, STAGE_RESULT_SCHEMA_ID)
        if stage["outcome"] != "pass":
            raise BenchmarkError(
                f"shadow collection stage is not green: {stage_path}"
            )
        duration = stage["duration_ns"]
        if type(duration) is not int or duration < 0:
            raise BenchmarkError(
                f"shadow collection duration is invalid: {stage_path}"
            )
        total += duration
    return total


def build_phase0_baseline_report(
    *,
    legacy_summary_path: Path,
    stage_attribution_path: Path,
    shadow_coverage_paths: Sequence[Path],
    pytest_observation_path: Path,
    observation_binding_path: Path,
) -> dict[str, Any]:
    """Close Phase-0 total, stage, collection, and per-node baseline evidence."""

    legacy = _load_expected_schema(
        legacy_summary_path,
        BENCHMARK_SUMMARY_SCHEMA_ID,
    )
    stage_attribution = _load_expected_schema(
        stage_attribution_path,
        LEGACY_STAGE_ATTRIBUTION_SCHEMA_ID,
    )
    if len(shadow_coverage_paths) < 5:
        raise BenchmarkError("Phase-0 report requires at least five shadow closures")
    shadows = [
        _load_expected_schema(path, SHADOW_COVERAGE_SCHEMA_ID)
        for path in shadow_coverage_paths
    ]
    observation_path_bytes = pytest_observation_path.read_bytes()
    observation = _load_expected_schema(
        pytest_observation_path,
        PYTEST_OBSERVATION_SCHEMA_ID,
    )
    binding = _load_expected_schema(
        observation_binding_path,
        PYTEST_OBSERVATION_BINDING_SCHEMA_ID,
    )

    source_digest = legacy["source_identity_digest"]
    if not isinstance(source_digest, str):
        raise BenchmarkError("legacy source identity digest is invalid")
    if stage_attribution["source_identity_digest"] != source_digest:
        raise BenchmarkError("stage attribution source identity drifted")
    if stage_attribution["terminal_status"] != "pass":
        raise BenchmarkError("stage attribution is not green")
    first_shadow_identity = _shadow_identity(shadows[0])
    for index, shadow in enumerate(shadows, start=1):
        if shadow["terminal_status"] != "pass":
            raise BenchmarkError(f"shadow closure {index} is not green")
        if shadow["source_identity_digest"] != source_digest:
            raise BenchmarkError(f"shadow closure {index} source identity drifted")
        if _shadow_identity(shadow) != first_shadow_identity:
            raise BenchmarkError(f"shadow closure {index} collection identity drifted")

    if binding["source_identity_digest"] != source_digest:
        raise BenchmarkError("pytest observation binding source identity drifted")
    bound_source = binding["source_identity"]
    if not isinstance(bound_source, dict) or sha256_digest(
        canonical_json_bytes(bound_source)
    ) != source_digest:
        raise BenchmarkError("pytest observation binding source payload is invalid")
    if (
        binding["observation_self_digest"] != observation["self_digest"]
        or binding["observation_document_digest"]
        != sha256_digest(observation_path_bytes)
        or binding["invocation_id"] != observation["invocation_id"]
    ):
        raise BenchmarkError("pytest observation binding does not match the document")
    collection = observation["collection"]
    if not isinstance(collection, list):
        raise BenchmarkError("pytest observation collection is invalid")
    observation_collection_digest = sha256_digest(
        canonical_json_bytes(collection)
    )
    if (
        binding["collection_digest"] != observation_collection_digest
        or observation_collection_digest
        != shadows[0]["general_collection_digest"]
    ):
        raise BenchmarkError("pytest observation collection drifted from shadow G")

    required_nodes = shadows[0]["distinct_required_nodes"]
    if not isinstance(required_nodes, list) or any(
        not isinstance(node_id, str) for node_id in required_nodes
    ):
        raise BenchmarkError("shadow distinct node set is invalid")
    observed_nodes = [
        item.get("node_id") for item in collection if isinstance(item, dict)
    ]
    if observed_nodes != required_nodes:
        raise BenchmarkError("pytest observation does not equal distinct coverage")
    raw_node_results = observation["node_results"]
    if not isinstance(raw_node_results, list):
        raise BenchmarkError("pytest observation node results are invalid")
    node_results: dict[str, Mapping[str, Any]] = {}
    for raw in raw_node_results:
        if not isinstance(raw, dict) or not isinstance(raw.get("node_id"), str):
            raise BenchmarkError("pytest observation contains an invalid node result")
        node_id = raw["node_id"]
        if node_id in node_results:
            raise BenchmarkError(f"pytest observation duplicates node {node_id!r}")
        if type(raw.get("duration_ns")) is not int or raw["duration_ns"] < 0:
            raise BenchmarkError(f"pytest node duration is invalid: {node_id}")
        node_results[node_id] = raw
    if sorted(node_results) != required_nodes:
        raise BenchmarkError("pytest result node set does not close required coverage")
    if observation["session_exit_code"] != 0:
        raise BenchmarkError("pytest observation process is not green")

    owner_records = shadows[0]["shadow_owners"]
    legacy_multiset = shadows[0]["legacy_execution_multiset"]
    if not isinstance(owner_records, list) or not isinstance(legacy_multiset, list):
        raise BenchmarkError("shadow ownership evidence is invalid")
    qualification_nodes = {
        item["node_id"]
        for item in owner_records
        if isinstance(item, dict)
        and item.get("owner") == "architecture_qualification_premerge"
    }
    harness_nodes = {
        item["node_id"]
        for item in legacy_multiset
        if isinstance(item, dict)
        and item.get("stage_id") == "architecture_qualification_harness"
    }
    scenario_nodes = {
        item["node_id"]
        for item in legacy_multiset
        if isinstance(item, dict)
        and item.get("stage_id") == "architecture_qualification_scenario"
    }
    if qualification_nodes != harness_nodes | scenario_nodes:
        raise BenchmarkError("qualification owner and legacy multiset sets drifted")

    def node_duration(nodes: set[str]) -> int:
        return sum(int(node_results[node_id]["duration_ns"]) for node_id in nodes)

    duplicate_duration_ns = node_duration(qualification_nodes)
    harness_duplicate_duration_ns = node_duration(harness_nodes)
    scenario_duplicate_duration_ns = node_duration(scenario_nodes)
    outcome_counts: dict[str, int] = {}
    module_durations: dict[str, int] = {}
    for node_id, result in node_results.items():
        outcome = result.get("outcome")
        if not isinstance(outcome, str):
            raise BenchmarkError(f"pytest node outcome is invalid: {node_id}")
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        module = node_id.split("::", 1)[0]
        module_durations[module] = module_durations.get(module, 0) + int(
            result["duration_ns"]
        )
    top_nodes = [
        {
            "node_id": node_id,
            "duration_ns": int(result["duration_ns"]),
            "outcome": result["outcome"],
            "qualification_owned": node_id in qualification_nodes,
        }
        for node_id, result in sorted(
            node_results.items(),
            key=lambda item: (-int(item[1]["duration_ns"]), item[0]),
        )[:25]
    ]
    top_modules = [
        {"test_module": module, "duration_ns": duration}
        for module, duration in sorted(
            module_durations.items(),
            key=lambda item: (-item[1], item[0]),
        )[:25]
    ]

    statistics_payload = legacy["statistics"]
    if not isinstance(statistics_payload, dict):
        raise BenchmarkError("legacy statistics are invalid")
    cold_statistics = statistics_payload.get("cold")
    warm_statistics = statistics_payload.get("warm")
    if not isinstance(cold_statistics, dict) or not isinstance(
        warm_statistics,
        dict,
    ):
        raise BenchmarkError("legacy cold/warm statistics are invalid")
    cold_median_ns = cold_statistics.get("median_ns")
    warm_median_ns = warm_statistics.get("median_ns")
    if type(cold_median_ns) not in {int, float} or type(warm_median_ns) not in {
        int,
        float,
    }:
        raise BenchmarkError("legacy median timing is invalid")
    cold_median_ns = int(cold_median_ns)
    warm_median_ns = int(warm_median_ns)

    stage_rows = stage_attribution["stages"]
    if not isinstance(stage_rows, list):
        raise BenchmarkError("stage attribution rows are invalid")
    stage_breakdown: list[dict[str, object]] = []
    for row in stage_rows:
        if not isinstance(row, dict):
            raise BenchmarkError("stage attribution row is invalid")
        duration = row.get("duration_ns")
        if type(duration) is not int or duration < 0:
            raise BenchmarkError("stage attribution duration is invalid")
        stage_breakdown.append(
            {
                "stage_id": row.get("stage_id"),
                "duration_ns": duration,
                "outcome": row.get("outcome"),
                "cold_median_share": round(duration / cold_median_ns, 6),
            }
        )
    compatibility_duration_ns = next(
        int(row["duration_ns"])
        for row in stage_breakdown
        if row["stage_id"] == "compatibility_audit"
    )
    planning_samples = [
        _shadow_collection_overhead_ns(path) for path in shadow_coverage_paths
    ]
    planning_median_ns = int(statistics.median(planning_samples))
    dedup_projection_ns = max(0, cold_median_ns - duplicate_duration_ns)
    theoretical_dedup_audit_projection_ns = max(
        0,
        dedup_projection_ns - compatibility_duration_ns,
    )
    target_25_percent_ns = round(cold_median_ns * 0.75)

    document = seal_document(
        PHASE0_BASELINE_SCHEMA_ID,
        {
            "phase_id": "phase0_legacy_measurement_and_shadow",
            "source_identity_digest": source_digest,
            "host_identity": legacy["host_identity"],
            "toolchain_identity": legacy["toolchain_identity"],
            "cache_control": legacy["cache_control"],
            "legacy_baseline": {
                "summary_digest": legacy["self_digest"],
                "valid_pair_count": statistics_payload["valid_pair_count"],
                "cold": cold_statistics,
                "warm": warm_statistics,
            },
            "stage_breakdown": stage_breakdown,
            "collection_closure": {
                "shadow_sample_count": len(shadows),
                "general_node_count": len(required_nodes),
                "qualification_harness_node_count": len(harness_nodes),
                "qualification_scenario_node_count": len(scenario_nodes),
                "structural_duplicate_count": len(
                    shadows[0]["structural_duplicates"]
                ),
                "general_collection_digest": shadows[0][
                    "general_collection_digest"
                ],
                "qualification_harness_collection_digest": shadows[0][
                    "qualification_harness_collection_digest"
                ],
                "qualification_scenario_collection_digest": shadows[0][
                    "qualification_scenario_collection_digest"
                ],
                "distinct_coverage_digest": shadows[0][
                    "distinct_coverage_digest"
                ],
                "planning_sample_duration_ns": planning_samples,
                "planning_median_duration_ns": planning_median_ns,
                "planning_median_share": round(
                    planning_median_ns / cold_median_ns,
                    6,
                ),
                "frontend_commands": shadows[0].get("frontend_commands"),
            },
            "node_critical_paths": {
                "observation_self_digest": observation["self_digest"],
                "observation_document_digest": binding[
                    "observation_document_digest"
                ],
                "result_count": len(node_results),
                "outcome_counts": {
                    key: outcome_counts[key] for key in sorted(outcome_counts)
                },
                "node_duration_total_ns": sum(
                    int(result["duration_ns"]) for result in node_results.values()
                ),
                "top_nodes": top_nodes,
                "top_test_modules": top_modules,
            },
            "duplicate_node_cost": {
                "node_count": len(qualification_nodes),
                "general_duplicate_duration_ns": duplicate_duration_ns,
                "harness_node_count": len(harness_nodes),
                "harness_general_duplicate_duration_ns": (
                    harness_duplicate_duration_ns
                ),
                "scenario_node_count": len(scenario_nodes),
                "scenario_general_duplicate_duration_ns": (
                    scenario_duplicate_duration_ns
                ),
                "estimate_basis": (
                    "same-source general node durations; stricter qualification "
                    "execution remains required"
                ),
            },
            "critical_path_assessment": {
                "cold_median_ns": cold_median_ns,
                "warm_median_ns": warm_median_ns,
                "cold_warm_delta_ns": warm_median_ns - cold_median_ns,
                "target_25_percent_ns": target_25_percent_ns,
                "dedup_only_serial_projection_ns": dedup_projection_ns,
                "dedup_only_reduction_fraction": round(
                    duplicate_duration_ns / cold_median_ns,
                    6,
                ),
                "dedup_plus_full_audit_ceiling_projection_ns": (
                    theoretical_dedup_audit_projection_ns
                ),
                "remaining_gap_to_25_percent_after_dedup_ns": max(
                    0,
                    dedup_projection_ns - target_25_percent_ns,
                ),
                "five_minute_target_ns": 300_000_000_000,
                "seven_minute_target_ns": 420_000_000_000,
            },
            "raw_evidence": {
                "legacy_summary_path": str(legacy_summary_path),
                "stage_attribution_path": str(stage_attribution_path),
                "shadow_coverage_paths": [
                    str(path) for path in shadow_coverage_paths
                ],
                "pytest_observation_path": str(pytest_observation_path),
                "observation_binding_path": str(observation_binding_path),
                "stage_attribution_digest": stage_attribution["self_digest"],
                "shadow_coverage_digests": [
                    shadow["self_digest"] for shadow in shadows
                ],
                "observation_binding_digest": binding["self_digest"],
            },
        },
    )
    return document
