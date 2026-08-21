from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate import benchmark  # noqa: E402
from scripts.test_gate.benchmark import (  # noqa: E402
    BenchmarkError,
    build_legacy_baseline_summary,
    build_phase0_baseline_report,
    run_legacy_sample,
    run_legacy_stage_attribution,
)
from scripts.test_gate.config import load_config  # noqa: E402
from scripts.test_gate.model import (  # noqa: E402
    BENCHMARK_SUMMARY_SCHEMA_ID,
    LEGACY_SAMPLE_SCHEMA_ID,
    LEGACY_STAGE_ATTRIBUTION_SCHEMA_ID,
    OPTIMIZED_SAMPLE_SCHEMA_ID,
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
from scripts.test_gate.optimized_benchmark import (  # noqa: E402
    build_optimized_benchmark_summary,
    host_activity_delta,
)
from scripts.test_gate.runner import ProcessResult, StreamCapture  # noqa: E402
from scripts.test_gate.source import SourceIdentity  # noqa: E402

CONFIG_PATH = REPOSITORY_ROOT / "scripts/test-gate.toml"


def _source_identity(digest_seed: str = "one") -> SourceIdentity:
    return SourceIdentity(
        commit="a" * 40,
        tracked_diff_digest=f"sha256:{digest_seed}",
        tracked_dirty_paths=(),
        relevant_untracked_sources=(),
        configurations=(),
        locks=(),
        toolchains=(),
    )


def _process(
    *,
    outcome: str = "pass",
    duration_ns: int = 1_000_000_000,
    stdout_tail: str = "",
) -> ProcessResult:
    empty = StreamCapture(
        digest="sha256:e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855",
        total_bytes=0,
        tail="",
    )
    stdout = StreamCapture(
        digest=empty.digest,
        total_bytes=len(stdout_tail.encode()),
        tail=stdout_tail,
    )
    return ProcessResult(
        argv=("./scripts/check-mainline.sh",),
        cwd=str(REPOSITORY_ROOT),
        outcome=outcome,
        exit_code=0 if outcome == "pass" else 1,
        started_monotonic_ns=100,
        duration_ns=duration_ns,
        stdout=stdout,
        stderr=empty,
        timed_out=False,
        term_sent=False,
        kill_sent=False,
        error=None,
    )


def test_legacy_wrapper_executes_frozen_comparison_and_never_turns_failure_green(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_identity()
    monkeypatch.setattr(
        benchmark,
        "collect_source_identity",
        lambda root: source,
    )
    monkeypatch.setattr(
        benchmark,
        "collect_host_identity",
        lambda: {"fingerprint": "sha256:host"},
    )
    observed_commands: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], **kwargs: object) -> ProcessResult:
        del kwargs
        observed_commands.append(command)
        return _process(outcome="fail")

    monkeypatch.setattr(benchmark, "run_command", fake_run)
    result = run_legacy_sample(
        repo_root=REPOSITORY_ROOT,
        output_root=tmp_path / "legacy-fail",
        invocation_id="sample-1",
        sample_kind="cold",
        sample_index=1,
    )

    assert observed_commands == [("./scripts/check-mainline-legacy.sh",)]
    assert result.functional_green is False
    assert result.document["functional_green"] is False
    assert result.document["process_result"]["outcome"] == "fail"
    published = load_canonical_document_bytes(
        (result.output_root / "legacy-sample.json").read_bytes()
    )
    assert published == result.document


def test_legacy_wrapper_invalidates_source_drift_even_when_process_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identities = iter((_source_identity("before"), _source_identity("after")))
    monkeypatch.setattr(
        benchmark,
        "collect_source_identity",
        lambda root: next(identities),
    )
    monkeypatch.setattr(
        benchmark,
        "collect_host_identity",
        lambda: {"fingerprint": "sha256:host"},
    )
    monkeypatch.setattr(benchmark, "run_command", lambda *args, **kwargs: _process())

    result = run_legacy_sample(
        repo_root=REPOSITORY_ROOT,
        output_root=tmp_path / "legacy-drift",
        invocation_id="sample-drift",
        sample_kind="warm",
        sample_index=1,
    )
    assert result.functional_green is False
    assert result.document["process_result"]["source_drift"] is True


def test_stage_attribution_preserves_exact_order_and_fail_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(CONFIG_PATH)
    source = _source_identity()
    monkeypatch.setattr(benchmark, "collect_source_identity", lambda root: source)
    observed: list[tuple[tuple[str, ...], Path]] = []

    def fake_run(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        **kwargs: object,
    ) -> ProcessResult:
        del kwargs
        observed.append((argv, cwd))
        result = _process(
            duration_ns=(len(observed) + 1) * 1_000_000_000,
            stdout_tail=(
                "2650 passed in 718.96s"
                if argv[:3] == ("uv", "run", "pytest")
                else ""
            ),
        )
        return ProcessResult(
            **{
                **result.__dict__,
                "argv": argv,
                "cwd": str(cwd),
            }
        )

    monkeypatch.setattr(benchmark, "run_command", fake_run)
    result = run_legacy_stage_attribution(
        repo_root=REPOSITORY_ROOT,
        output_root=tmp_path / "stage-attribution",
        invocation_id="attribution-1",
        config=config,
    )

    assert result.terminal_status == "pass"
    assert [item["stage_id"] for item in result.document["stages"]] == list(
        config.profile("mainline_authoritative").stage_ids
    )
    assert [argv for argv, _ in observed][0] == config.stage("ruff_source").argv
    assert [argv for argv, _ in observed][-2:] == [
        config.stage("web_ui_test").argv,
        config.stage("web_ui_build").argv,
    ]
    pytest_stage = next(
        item
        for item in result.document["stages"]
        if item["stage_id"] == "general_non_live_pytest"
    )
    assert pytest_stage["pytest_reported_seconds"] == 718.96
    assert pytest_stage["process_overhead_seconds"] >= 0


def test_stage_attribution_stops_at_the_first_failed_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(CONFIG_PATH)
    source = _source_identity()
    monkeypatch.setattr(benchmark, "collect_source_identity", lambda root: source)
    calls = 0

    def fake_run(*args: object, **kwargs: object) -> ProcessResult:
        nonlocal calls
        del args, kwargs
        calls += 1
        return _process(outcome="fail" if calls == 3 else "pass")

    monkeypatch.setattr(benchmark, "run_command", fake_run)
    result = run_legacy_stage_attribution(
        repo_root=REPOSITORY_ROOT,
        output_root=tmp_path / "stage-failure",
        invocation_id="attribution-failure",
        config=config,
    )

    assert result.terminal_status == "fail"
    assert calls == 3
    assert result.document["first_failing_stage"] == "compatibility_audit"
    assert [item["stage_id"] for item in result.document["stages"]] == [
        "ruff_source",
        "ruff_compatibility_audit",
        "compatibility_audit",
    ]


def _sample_document(
    *,
    invocation_id: str,
    sample_kind: str,
    sample_index: int,
    duration_ns: int,
    functional_green: bool = True,
    host: str = "host-a",
) -> dict[str, object]:
    source = _source_identity().as_dict()
    return seal_document(
        LEGACY_SAMPLE_SCHEMA_ID,
        {
            "invocation_id": invocation_id,
            "sample_kind": sample_kind,
            "sample_index": sample_index,
            "cache_control": "process_only",
            "source_identity": source,
            "source_identity_digest": _source_identity().digest,
            "host_identity": {"fingerprint": host},
            "command": ["./scripts/check-mainline.sh"],
            "process_result": {"duration_ns": duration_ns},
            "functional_green": functional_green,
        },
    )


def test_baseline_summary_requires_five_green_same_identity_pairs(
    tmp_path: Path,
) -> None:
    sample_paths: list[Path] = []
    for index in range(1, 6):
        for kind, duration in (
            ("cold", index * 10),
            ("warm", index * 5),
        ):
            document = _sample_document(
                invocation_id=f"{kind}-{index}",
                sample_kind=kind,
                sample_index=index,
                duration_ns=duration,
            )
            path = tmp_path / f"{kind}-{index}.json"
            path.write_bytes(canonical_document_bytes(document))
            sample_paths.append(path)

    summary = build_legacy_baseline_summary(sample_paths)
    assert summary["statistics"]["valid_pair_count"] == 5
    assert summary["statistics"]["cold"]["median_ns"] == 30
    assert summary["statistics"]["warm"]["median_ns"] == 15
    assert summary["cache_control"] == "process_only"

    failed = _sample_document(
        invocation_id="warm-5",
        sample_kind="warm",
        sample_index=5,
        duration_ns=25,
        functional_green=False,
    )
    sample_paths[-1].write_bytes(canonical_document_bytes(failed))
    with pytest.raises(BenchmarkError, match="at least five valid pairs"):
        build_legacy_baseline_summary(sample_paths)


def _optimized_sample_document(
    *,
    sample_kind: str,
    sample_index: int,
    duration_ns: int,
) -> dict[str, object]:
    source = _source_identity().as_dict()
    overhead_ns = 20
    stage_duration_ns = {
        "ruff_source": 1,
        "ruff_compatibility_audit": 1,
        "compatibility_audit": 1,
        "architecture_qualification_premerge": 1,
        "general_non_live_pytest": duration_ns - overhead_ns - 6,
        "web_ui_test": 1,
        "web_ui_build": 1,
    }
    return seal_document(
        OPTIMIZED_SAMPLE_SCHEMA_ID,
        {
            "invocation_id": f"optimized-{sample_kind}-{sample_index}",
            "sample_kind": sample_kind,
            "sample_index": sample_index,
            "cache_control": "process_only",
            "source_identity": source,
            "source_identity_digest": _source_identity().digest,
            "source_recheck_digest": _source_identity().digest,
            "source_drift": False,
            "host_identity": {"fingerprint": "host-a"},
            "worker_policy": {"mode": "fixed_parallel", "workers": 3},
            "plan_digest": f"sha256:plan-{sample_kind}-{sample_index}",
            "receipt_digest": (
                f"sha256:receipt-{sample_kind}-{sample_index}"
            ),
            "terminal_status": "pass",
            "functional_green": True,
            "timing": {
                "total_duration_ns": duration_ns,
                "stage_duration_ns": stage_duration_ns,
                "stage_total_ns": duration_ns - overhead_ns,
                "orchestration_overhead_ns": overhead_ns,
                "orchestration_overhead_ppm": round(
                    overhead_ns * 1_000_000 / duration_ns
                ),
                "general_partitions": {},
            },
            "coverage": {
                "collection_digest": "sha256:collection",
                "collected_node_count": 10,
                "executed_node_count": 10,
                "outcome_projection_digest": "sha256:outcomes",
                "qualification_status": "verified",
                "frontend_outcomes": {
                    "web_ui_build": "pass",
                    "web_ui_test": "pass",
                },
                "offline_verification": "pass",
                "verification_error_digest": None,
            },
            "host_activity": {
                "delta": {
                    "cpu_utilization_ppm": 500_000,
                    "cpu_iowait_ppm": 10_000,
                    "pressure_stall_ppm": {
                        "cpu": {"some": 20_000},
                        "io": {"some": 5_000},
                    },
                }
            },
        },
    )


def test_optimized_summary_closes_threshold_overhead_and_contention(
    tmp_path: Path,
) -> None:
    paths: list[Path] = []
    for index in range(1, 6):
        for sample_kind, duration_ns in (
            ("cold", 670 + index * 10),
            ("warm", 580 + index * 10),
        ):
            path = tmp_path / f"{sample_kind}-{index}.json"
            path.write_bytes(
                canonical_document_bytes(
                    _optimized_sample_document(
                        sample_kind=sample_kind,
                        sample_index=index,
                        duration_ns=duration_ns,
                    )
                )
            )
            paths.append(path)
    source = _source_identity().as_dict()
    legacy = seal_document(
        BENCHMARK_SUMMARY_SCHEMA_ID,
        {
            "source_identity_digest": _source_identity().digest,
            "host_identity": {"fingerprint": "host-a"},
            "toolchain_identity": source["toolchains"],
            "cache_control": "process_only",
            "cold_samples": [],
            "warm_samples": [],
            "statistics": {
                "cold": {"median_ns": 1000},
                "warm": {"median_ns": 900},
            },
        },
    )
    legacy_path = tmp_path / "legacy-summary.json"
    legacy_path.write_bytes(canonical_document_bytes(legacy))

    summary = build_optimized_benchmark_summary(
        sample_paths=paths,
        legacy_summary_path=legacy_path,
    )

    assert summary["statistics"]["valid_pair_count"] == 5
    assert summary["baseline_comparison"]["cold_reduction_ppm"] == 300_000
    assert summary["baseline_comparison"]["warm_reduction_ppm"] > 300_000
    assert summary["baseline_comparison"]["threshold_met"] is True
    assert summary["planning_overhead"]["threshold_met"] is True
    assert summary["contention"]["cpu_utilization_ppm"]["median"] == 500_000


def test_host_activity_delta_reports_cpu_and_io_pressure() -> None:
    before = {
        "monotonic_ns": 1_000_000_000,
        "load_average_milli": [100, 200, 300],
        "cpu_ticks": {"total": 100, "idle": 50, "iowait": 5},
        "pressure_total_us": {
            "cpu": {"some": 1_000, "full": 100},
            "io": {"some": 2_000, "full": 200},
        },
    }
    after = {
        "monotonic_ns": 2_000_000_000,
        "load_average_milli": [200, 300, 400],
        "cpu_ticks": {"total": 200, "idle": 80, "iowait": 10},
        "pressure_total_us": {
            "cpu": {"some": 101_000, "full": 10_100},
            "io": {"some": 22_000, "full": 2_200},
        },
    }

    delta = host_activity_delta(before, after)

    assert delta["cpu_utilization_ppm"] == 650_000
    assert delta["cpu_iowait_ppm"] == 50_000
    assert delta["pressure_stall_ppm"]["cpu"]["some"] == 100_000
    assert delta["pressure_stall_ppm"]["io"]["some"] == 20_000


def _write_document(path: Path, document: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_document_bytes(document))
    return path


def _fixture_stage_document(stage_id: str, duration_ns: int) -> dict[str, object]:
    return seal_document(
        STAGE_RESULT_SCHEMA_ID,
        {
            "invocation_id": "phase0-fixture",
            "plan_digest": "sha256:plan",
            "stage_id": stage_id,
            "argv": ["pytest"],
            "cwd": "/tmp",
            "environment_digest": "sha256:environment",
            "outcome": "pass",
            "started_monotonic_ns": 1,
            "duration_ns": duration_ns,
            "exit_code": 0,
            "stdout_digest": "sha256:stdout",
            "stdout_tail": "",
            "stderr_digest": "sha256:stderr",
            "stderr_tail": "",
        },
    )


def test_phase0_report_closes_total_collection_and_node_evidence(
    tmp_path: Path,
) -> None:
    source_payload = {"commit": "fixture"}
    source_digest = sha256_digest(canonical_json_bytes(source_payload))
    legacy = seal_document(
        BENCHMARK_SUMMARY_SCHEMA_ID,
        {
            "source_identity_digest": source_digest,
            "host_identity": {"fingerprint": "host"},
            "toolchain_identity": [],
            "cache_control": "process_only",
            "cold_samples": [],
            "warm_samples": [],
            "statistics": {
                "valid_pair_count": 5,
                "cold": {
                    "count": 5,
                    "median_ns": 1_000,
                    "mad_ns": 10,
                    "min_ns": 980,
                    "max_ns": 1_020,
                },
                "warm": {
                    "count": 5,
                    "median_ns": 990,
                    "mad_ns": 10,
                    "min_ns": 970,
                    "max_ns": 1_010,
                },
            },
        },
    )
    legacy_path = _write_document(tmp_path / "legacy.json", legacy)
    attribution = seal_document(
        LEGACY_STAGE_ATTRIBUTION_SCHEMA_ID,
        {
            "invocation_id": "phase0-fixture",
            "source_identity_digest": source_digest,
            "stages": [
                {
                    "stage_id": "compatibility_audit",
                    "duration_ns": 50,
                    "outcome": "pass",
                },
                {
                    "stage_id": "general_non_live_pytest",
                    "duration_ns": 800,
                    "outcome": "pass",
                },
            ],
            "terminal_status": "pass",
        },
    )
    attribution_path = _write_document(
        tmp_path / "attribution.json",
        attribution,
    )

    general_collection = [
        {"node_id": "node-a", "markers": []},
        {"node_id": "node-b", "markers": []},
    ]
    general_digest = sha256_digest(canonical_json_bytes(general_collection))
    legacy_multiset = [
        {"node_id": "node-a", "stage_id": "general_non_live_pytest"},
        {"node_id": "node-b", "stage_id": "architecture_qualification_harness"},
        {"node_id": "node-b", "stage_id": "general_non_live_pytest"},
    ]
    shadow_paths: list[Path] = []
    for index in range(5):
        shadow = seal_document(
            SHADOW_COVERAGE_SCHEMA_ID,
            {
                "invocation_id": f"shadow-{index}",
                "source_identity_digest": source_digest,
                "general_collection_digest": general_digest,
                "qualification_harness_collection_digest": "sha256:harness",
                "qualification_scenario_collection_digest": "sha256:scenario",
                "legacy_execution_multiset": legacy_multiset,
                "legacy_execution_multiset_digest": sha256_digest(
                    canonical_json_bytes(legacy_multiset)
                ),
                "distinct_required_nodes": ["node-a", "node-b"],
                "distinct_coverage_digest": sha256_digest(
                    canonical_json_bytes(["node-a", "node-b"])
                ),
                "structural_duplicates": [
                    {
                        "node_id": "node-b",
                        "legacy_stage_ids": [
                            "architecture_qualification_harness",
                            "general_non_live_pytest",
                        ],
                    }
                ],
                "shadow_owners": [
                    {
                        "node_id": "node-a",
                        "owner": "general_non_live_pytest",
                    },
                    {
                        "node_id": "node-b",
                        "owner": "architecture_qualification_premerge",
                    },
                ],
                "forbidden_nodes": [],
                "terminal_status": "pass",
                "frontend_commands": [],
            },
        )
        shadow_path = _write_document(
            tmp_path / f"shadow-{index}" / "shadow-coverage.json",
            shadow,
        )
        shadow_paths.append(shadow_path)
        for stage_id in (
            "general_collection",
            "qualification_harness_collection",
            "qualification_scenario_collection",
        ):
            _write_document(
                shadow_path.parent / f"{stage_id}-stage.json",
                _fixture_stage_document(stage_id, 5),
            )

    phase = {
        "phase": "call",
        "outcome": "passed",
        "duration_ns": 1,
        "was_xfail": False,
        "failure_digest": None,
    }
    observation = seal_document(
        PYTEST_OBSERVATION_SCHEMA_ID,
        {
            "invocation_id": "observed-fixture",
            "role": "legacy_general",
            "mode": "execute",
            "pytest_argv": ["pytest"],
            "cwd": "/tmp",
            "collection": general_collection,
            "deselected": [],
            "node_results": [
                {
                    "node_id": "node-a",
                    "outcome": "pass",
                    "duration_ns": 100,
                    "phases": [phase],
                },
                {
                    "node_id": "node-b",
                    "outcome": "pass",
                    "duration_ns": 200,
                    "phases": [phase],
                },
            ],
            "session_exit_code": 0,
            "started_monotonic_ns": 1,
            "duration_ns": 300,
        },
    )
    observation_path = _write_document(
        tmp_path / "observation.json",
        observation,
    )
    observation_bytes = observation_path.read_bytes()
    binding = seal_document(
        PYTEST_OBSERVATION_BINDING_SCHEMA_ID,
        {
            "invocation_id": "observed-fixture",
            "source_identity": source_payload,
            "source_identity_digest": source_digest,
            "observation_self_digest": observation["self_digest"],
            "observation_document_digest": sha256_digest(observation_bytes),
            "collection_digest": general_digest,
            "pytest_argv": ["pytest"],
            "binding_basis": "fixture",
        },
    )
    binding_path = _write_document(tmp_path / "binding.json", binding)

    report = build_phase0_baseline_report(
        legacy_summary_path=legacy_path,
        stage_attribution_path=attribution_path,
        shadow_coverage_paths=shadow_paths,
        pytest_observation_path=observation_path,
        observation_binding_path=binding_path,
    )
    assert report["collection_closure"]["shadow_sample_count"] == 5
    assert report["collection_closure"]["general_node_count"] == 2
    assert report["duplicate_node_cost"]["node_count"] == 1
    assert report["duplicate_node_cost"]["general_duplicate_duration_ns"] == 200
    assert report["node_critical_paths"]["outcome_counts"] == {"pass": 2}
    assert report["critical_path_assessment"][
        "dedup_only_serial_projection_ns"
    ] == 800
