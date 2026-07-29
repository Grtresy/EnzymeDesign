"""Source-bound optimized mainline samples and paired performance reduction."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .authoritative_runner import (
    AuthoritativeRunnerError,
    MainlineCandidateRunResult,
    run_authoritative_shadow_candidate,
    verify_authoritative_candidate_output,
)
from .benchmark import BenchmarkError, collect_host_identity
from .config import TestGateConfig
from .model import (
    BENCHMARK_SUMMARY_SCHEMA_ID,
    OPTIMIZED_SAMPLE_SCHEMA_ID,
    PYTEST_OBSERVATION_SCHEMA_ID,
    canonical_document_bytes,
    canonical_json_bytes,
    load_canonical_document_bytes,
    seal_document,
    sha256_digest,
)
from .resource import DEFAULT_RESOURCE_MANIFEST_PATH
from .runner import publish_no_replace
from .source import collect_source_identity

OPTIMIZED_SAMPLE_FILENAME = "optimized-sample.json"
_PRESSURE_FILES = {
    "cpu": Path("/proc/pressure/cpu"),
    "io": Path("/proc/pressure/io"),
}
_STAGE_IDS = (
    "ruff_source",
    "ruff_compatibility_audit",
    "compatibility_audit",
    "architecture_qualification_premerge",
    "general_non_live_pytest",
    "web_ui_test",
    "web_ui_build",
)


@dataclass(frozen=True)
class OptimizedSampleResult:
    """One candidate run plus its canonical performance sample."""

    candidate: MainlineCandidateRunResult
    document: Mapping[str, Any]
    functional_green: bool


def _load_average_milli() -> list[int] | None:
    try:
        values = Path("/proc/loadavg").read_text(encoding="ascii").split()[:3]
        if len(values) != 3:
            return None
        return [round(float(value) * 1000) for value in values]
    except (OSError, ValueError):
        return None


def _cpu_ticks() -> dict[str, int] | None:
    try:
        values = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0]
        fields = values.split()
        if not fields or fields[0] != "cpu":
            return None
        counters = [int(value) for value in fields[1:]]
    except (OSError, ValueError, IndexError):
        return None
    if len(counters) < 5:
        return None
    return {
        "total": sum(counters),
        "idle": counters[3],
        "iowait": counters[4],
    }


def _pressure_totals(path: Path) -> dict[str, int | None]:
    totals: dict[str, int | None] = {"some": None, "full": None}
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except OSError:
        return totals
    for line in lines:
        fields = line.split()
        if not fields or fields[0] not in totals:
            continue
        total = next(
            (
                field.removeprefix("total=")
                for field in fields[1:]
                if field.startswith("total=")
            ),
            None,
        )
        if total is not None:
            try:
                totals[fields[0]] = int(total)
            except ValueError:
                totals[fields[0]] = None
    return totals


def collect_host_activity() -> dict[str, Any]:
    """Read monotonic host CPU and I/O contention counters without effects."""

    return {
        "monotonic_ns": time.monotonic_ns(),
        "load_average_milli": _load_average_milli(),
        "cpu_ticks": _cpu_ticks(),
        "pressure_total_us": {
            name: _pressure_totals(path)
            for name, path in sorted(_PRESSURE_FILES.items())
        },
    }


def _counter_delta(before: object, after: object) -> int | None:
    if (
        type(before) is not int
        or type(after) is not int
        or after < before
    ):
        return None
    return after - before


def host_activity_delta(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, Any]:
    """Reduce cumulative host counters to bounded per-sample contention."""

    duration_ns = _counter_delta(
        before.get("monotonic_ns"),
        after.get("monotonic_ns"),
    )
    before_ticks = before.get("cpu_ticks")
    after_ticks = after.get("cpu_ticks")
    cpu_total = cpu_idle = cpu_iowait = None
    if isinstance(before_ticks, dict) and isinstance(after_ticks, dict):
        cpu_total = _counter_delta(
            before_ticks.get("total"),
            after_ticks.get("total"),
        )
        cpu_idle = _counter_delta(
            before_ticks.get("idle"),
            after_ticks.get("idle"),
        )
        cpu_iowait = _counter_delta(
            before_ticks.get("iowait"),
            after_ticks.get("iowait"),
        )
    cpu_active = (
        None
        if (
            cpu_total is None
            or cpu_idle is None
            or cpu_iowait is None
        )
        else max(0, cpu_total - cpu_idle - cpu_iowait)
    )
    cpu_utilization_ppm = (
        None
        if cpu_total in {None, 0} or cpu_active is None
        else round(cpu_active * 1_000_000 / cpu_total)
    )
    cpu_iowait_ppm = (
        None
        if cpu_total in {None, 0} or cpu_iowait is None
        else round(cpu_iowait * 1_000_000 / cpu_total)
    )
    pressure_delta: dict[str, dict[str, int | None]] = {}
    pressure_stall_ppm: dict[str, dict[str, int | None]] = {}
    before_pressure = before.get("pressure_total_us")
    after_pressure = after.get("pressure_total_us")
    duration_us = (
        None if duration_ns is None else max(1, duration_ns // 1000)
    )
    for resource in sorted(_PRESSURE_FILES):
        resource_before = (
            before_pressure.get(resource)
            if isinstance(before_pressure, dict)
            else None
        )
        resource_after = (
            after_pressure.get(resource)
            if isinstance(after_pressure, dict)
            else None
        )
        pressure_delta[resource] = {}
        pressure_stall_ppm[resource] = {}
        for level in ("some", "full"):
            delta = _counter_delta(
                (
                    resource_before.get(level)
                    if isinstance(resource_before, dict)
                    else None
                ),
                (
                    resource_after.get(level)
                    if isinstance(resource_after, dict)
                    else None
                ),
            )
            pressure_delta[resource][level] = delta
            pressure_stall_ppm[resource][level] = (
                None
                if delta is None or duration_us is None
                else round(delta * 1_000_000 / duration_us)
            )
    return {
        "duration_ns": duration_ns,
        "cpu_total_ticks": cpu_total,
        "cpu_active_ticks": cpu_active,
        "cpu_iowait_ticks": cpu_iowait,
        "cpu_utilization_ppm": cpu_utilization_ppm,
        "cpu_iowait_ppm": cpu_iowait_ppm,
        "pressure_delta_us": pressure_delta,
        "pressure_stall_ppm": pressure_stall_ppm,
        "load_average_milli_before": before.get("load_average_milli"),
        "load_average_milli_after": after.get("load_average_milli"),
    }


def _load_observation(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        document = load_canonical_document_bytes(path.read_bytes())
    except (OSError, ValueError):
        return None
    if document.get("schema_id") != PYTEST_OBSERVATION_SCHEMA_ID:
        return None
    return document


def _partition_timing(output_root: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for partition in ("parallel", "serial"):
        document = _load_observation(
            output_root / f"general-{partition}-observation.json"
        )
        result[partition] = (
            None
            if document is None
            else {
                "duration_ns": document["duration_ns"],
                "node_count": len(document["node_results"]),
                "observation_digest": document["self_digest"],
            }
        )
    return result


def run_optimized_sample(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    sample_kind: str,
    sample_index: int,
    workers: int,
    resource_manifest_path: Path = DEFAULT_RESOURCE_MANIFEST_PATH,
) -> OptimizedSampleResult:
    """Run one fresh candidate process graph and publish benchmark evidence."""

    if sample_kind not in {"cold", "warm"}:
        raise BenchmarkError("sample_kind must be cold or warm")
    if type(sample_index) is not int or sample_index < 1:
        raise BenchmarkError("sample_index must be a positive integer")
    root = repo_root.resolve(strict=True)
    source_before = collect_source_identity(root)
    host_identity = collect_host_identity()
    activity_before = collect_host_activity()
    candidate = run_authoritative_shadow_candidate(
        repo_root=root,
        output_root=output_root,
        config=config,
        invocation_id=invocation_id,
        resource_manifest_path=resource_manifest_path,
        workers=workers,
    )
    activity_after = collect_host_activity()
    source_after = collect_source_identity(root)
    source_drift = source_before.digest != source_after.digest
    verification_status = "pass"
    verification_error_digest: str | None = None
    try:
        verify_authoritative_candidate_output(
            output_root=candidate.output_root,
            repo_root=root,
            config=config,
            current_source_identity_digest=source_after.digest,
        )
    except AuthoritativeRunnerError as exc:
        verification_status = "fail"
        verification_error_digest = sha256_digest(
            str(exc).encode("utf-8", errors="replace")
        )
    receipt = candidate.receipt
    timing = receipt["timing"]
    total_duration_ns = int(timing["total_duration_ns"])
    stage_duration_ns = {
        str(stage_id): int(duration_ns)
        for stage_id, duration_ns in timing["stage_duration_ns"].items()
    }
    stage_total_ns = sum(stage_duration_ns.values())
    orchestration_overhead_ns = max(0, total_duration_ns - stage_total_ns)
    orchestration_overhead_ppm = (
        0
        if total_duration_ns == 0
        else round(orchestration_overhead_ns * 1_000_000 / total_duration_ns)
    )
    coverage = receipt["coverage"]
    outcome_projection = [
        {
            "node_id": item["node_id"],
            "owner": item["owner"],
            "outcome": item["outcome"],
        }
        for item in coverage["node_results"]
    ]
    functional_green = (
        candidate.terminal_status == "pass"
        and not source_drift
        and verification_status == "pass"
    )
    document = seal_document(
        OPTIMIZED_SAMPLE_SCHEMA_ID,
        {
            "invocation_id": invocation_id,
            "sample_kind": sample_kind,
            "sample_index": sample_index,
            "cache_control": "process_only",
            "source_identity": source_before.as_dict(),
            "source_identity_digest": source_before.digest,
            "source_recheck_digest": source_after.digest,
            "source_drift": source_drift,
            "host_identity": host_identity,
            "worker_policy": dict(candidate.plan["worker_policy"]),
            "plan_digest": candidate.plan["self_digest"],
            "receipt_digest": receipt["self_digest"],
            "terminal_status": candidate.terminal_status,
            "functional_green": functional_green,
            "timing": {
                "total_duration_ns": total_duration_ns,
                "stage_duration_ns": stage_duration_ns,
                "stage_total_ns": stage_total_ns,
                "orchestration_overhead_ns": orchestration_overhead_ns,
                "orchestration_overhead_ppm": orchestration_overhead_ppm,
                "general_partitions": _partition_timing(
                    candidate.output_root
                ),
            },
            "coverage": {
                "collection_digest": coverage["collection_digest"],
                "collected_node_count": len(coverage["collected_nodes"]),
                "executed_node_count": len(coverage["executed_nodes"]),
                "outcome_projection_digest": sha256_digest(
                    canonical_json_bytes(outcome_projection)
                ),
                "qualification_status": receipt["qualification"]["status"],
                "frontend_outcomes": dict(receipt["frontend"]["outcomes"]),
                "offline_verification": verification_status,
                "verification_error_digest": verification_error_digest,
            },
            "host_activity": {
                "before": activity_before,
                "after": activity_after,
                "delta": host_activity_delta(
                    activity_before,
                    activity_after,
                ),
            },
        },
    )
    publish_no_replace(
        candidate.output_root / OPTIMIZED_SAMPLE_FILENAME,
        canonical_document_bytes(document),
    )
    return OptimizedSampleResult(
        candidate=candidate,
        document=document,
        functional_green=functional_green,
    )


def _load_sample(path: Path) -> dict[str, Any]:
    try:
        document = load_canonical_document_bytes(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise BenchmarkError(f"invalid optimized sample {path}: {exc}") from exc
    if document.get("schema_id") != OPTIMIZED_SAMPLE_SCHEMA_ID:
        raise BenchmarkError(f"unexpected optimized sample schema in {path}")
    return document


def _distribution(values: Sequence[int]) -> dict[str, object]:
    if not values:
        raise BenchmarkError("cannot summarize an empty optimized distribution")
    median = statistics.median(values)
    return {
        "count": len(values),
        "median_ns": median,
        "mad_ns": statistics.median(
            abs(value - median) for value in values
        ),
        "min_ns": min(values),
        "max_ns": max(values),
    }


def _integer_distribution(values: Sequence[int]) -> dict[str, object]:
    if not values:
        raise BenchmarkError("contention counters are unavailable")
    median = statistics.median(values)
    return {
        "count": len(values),
        "median": median,
        "mad": statistics.median(abs(value - median) for value in values),
        "min": min(values),
        "max": max(values),
    }


def _nested_int(
    document: Mapping[str, Any],
    *path: str,
) -> int | None:
    value: object = document
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if type(value) is int else None


def _reduction_ppm(baseline_ns: int, candidate_ns: int) -> int:
    if baseline_ns <= 0:
        raise BenchmarkError("baseline median must be positive")
    return round((baseline_ns - candidate_ns) * 1_000_000 / baseline_ns)


def build_optimized_benchmark_summary(
    *,
    sample_paths: Sequence[Path],
    legacy_summary_path: Path,
) -> dict[str, Any]:
    """Reduce five same-source cold/warm optimized pairs against legacy."""

    samples = [_load_sample(path) for path in sample_paths]
    try:
        legacy = load_canonical_document_bytes(legacy_summary_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise BenchmarkError(f"invalid legacy summary: {exc}") from exc
    if legacy.get("schema_id") != BENCHMARK_SUMMARY_SCHEMA_ID:
        raise BenchmarkError("legacy comparison summary schema is invalid")
    by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for sample in samples:
        sample_index = sample.get("sample_index")
        sample_kind = sample.get("sample_kind")
        if type(sample_index) is not int or sample_kind not in {"cold", "warm"}:
            raise BenchmarkError("optimized sample pair identity is invalid")
        key = (sample_index, sample_kind)
        if key in by_key:
            raise BenchmarkError(f"duplicate optimized sample key: {key!r}")
        by_key[key] = sample
    valid_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    invalid_samples: list[dict[str, object]] = []
    for index in sorted({key[0] for key in by_key}):
        cold = by_key.get((index, "cold"))
        warm = by_key.get((index, "warm"))
        if cold is None or warm is None:
            invalid_samples.append(
                {"sample_index": index, "reason": "missing_pair_member"}
            )
            continue
        identity_fields = (
            "source_identity_digest",
            "host_identity",
            "worker_policy",
            "cache_control",
            "coverage",
        )
        if any(cold[field] != warm[field] for field in identity_fields):
            invalid_samples.append(
                {"sample_index": index, "reason": "paired_identity_drift"}
            )
            continue
        if not cold["functional_green"] or not warm["functional_green"]:
            invalid_samples.append(
                {"sample_index": index, "reason": "functional_failure"}
            )
            continue
        valid_pairs.append((cold, warm))
    if len(valid_pairs) < 5:
        raise BenchmarkError(
            "optimized benchmark requires at least five valid pairs; "
            f"got {len(valid_pairs)}"
        )
    first = valid_pairs[0][0]
    common_fields = (
        "source_identity_digest",
        "host_identity",
        "worker_policy",
        "cache_control",
        "coverage",
    )
    for cold, warm in valid_pairs:
        for sample in (cold, warm):
            if any(sample[field] != first[field] for field in common_fields):
                raise BenchmarkError(
                    "optimized samples do not share one source/host/policy"
                )
    if (
        legacy["source_identity_digest"] != first["source_identity_digest"]
        or legacy["host_identity"] != first["host_identity"]
    ):
        raise BenchmarkError(
            "legacy and optimized summaries must share source and host identity"
        )

    def sample_record(sample: Mapping[str, Any]) -> dict[str, object]:
        return {
            "invocation_id": sample["invocation_id"],
            "sample_index": sample["sample_index"],
            "duration_ns": sample["timing"]["total_duration_ns"],
            "orchestration_overhead_ns": sample["timing"][
                "orchestration_overhead_ns"
            ],
            "orchestration_overhead_ppm": sample["timing"][
                "orchestration_overhead_ppm"
            ],
            "sample_digest": sample["self_digest"],
        }

    cold_samples = [sample_record(cold) for cold, _ in valid_pairs]
    warm_samples = [sample_record(warm) for _, warm in valid_pairs]
    cold_distribution = _distribution(
        [int(item["duration_ns"]) for item in cold_samples]
    )
    warm_distribution = _distribution(
        [int(item["duration_ns"]) for item in warm_samples]
    )
    stage_breakdown: dict[str, object] = {}
    for stage_id in _STAGE_IDS:
        stage_breakdown[stage_id] = {
            "cold": _distribution(
                [
                    int(cold["timing"]["stage_duration_ns"][stage_id])
                    for cold, _ in valid_pairs
                ]
            ),
            "warm": _distribution(
                [
                    int(warm["timing"]["stage_duration_ns"][stage_id])
                    for _, warm in valid_pairs
                ]
            ),
        }
    overhead_values = [
        int(sample["timing"]["orchestration_overhead_ppm"])
        for pair in valid_pairs
        for sample in pair
    ]
    overhead_distribution = _integer_distribution(overhead_values)
    contention_paths = {
        "cpu_utilization_ppm": ("delta", "cpu_utilization_ppm"),
        "cpu_iowait_ppm": ("delta", "cpu_iowait_ppm"),
        "cpu_pressure_some_ppm": (
            "delta",
            "pressure_stall_ppm",
            "cpu",
            "some",
        ),
        "io_pressure_some_ppm": (
            "delta",
            "pressure_stall_ppm",
            "io",
            "some",
        ),
    }
    contention: dict[str, object] = {}
    for name, path in contention_paths.items():
        values = [
            value
            for pair in valid_pairs
            for sample in pair
            if (
                value := _nested_int(sample["host_activity"], *path)
            )
            is not None
        ]
        contention[name] = _integer_distribution(values)
    legacy_cold = int(legacy["statistics"]["cold"]["median_ns"])
    legacy_warm = int(legacy["statistics"]["warm"]["median_ns"])
    candidate_cold = int(cold_distribution["median_ns"])
    candidate_warm = int(warm_distribution["median_ns"])
    cold_reduction = _reduction_ppm(legacy_cold, candidate_cold)
    warm_reduction = _reduction_ppm(legacy_warm, candidate_warm)
    overhead_median = int(overhead_distribution["median"])
    threshold_met = (
        cold_reduction >= 250_000
        and warm_reduction >= 250_000
        and overhead_median < 50_000
    )
    source_identity = first["source_identity"]
    return seal_document(
        BENCHMARK_SUMMARY_SCHEMA_ID,
        {
            "source_identity_digest": first["source_identity_digest"],
            "host_identity": first["host_identity"],
            "toolchain_identity": source_identity["toolchains"],
            "cache_control": "process_only",
            "cold_samples": cold_samples,
            "warm_samples": warm_samples,
            "statistics": {
                "valid_pair_count": len(valid_pairs),
                "cold": cold_distribution,
                "warm": warm_distribution,
            },
            "invalid_samples": invalid_samples,
            "candidate_profile": {
                "profile_id": "mainline_authoritative",
                "worker_policy": first["worker_policy"],
                "coverage": first["coverage"],
            },
            "stage_breakdown": stage_breakdown,
            "planning_overhead": {
                "ratio_ppm": overhead_distribution,
                "required_max_ppm": 50_000,
                "threshold_met": overhead_median < 50_000,
            },
            "contention": contention,
            "baseline_comparison": {
                "legacy_summary_digest": legacy["self_digest"],
                "legacy_cold_median_ns": legacy_cold,
                "legacy_warm_median_ns": legacy_warm,
                "candidate_cold_median_ns": candidate_cold,
                "candidate_warm_median_ns": candidate_warm,
                "cold_reduction_ppm": cold_reduction,
                "warm_reduction_ppm": warm_reduction,
                "required_reduction_ppm": 250_000,
                "threshold_met": threshold_met,
            },
        },
    )
