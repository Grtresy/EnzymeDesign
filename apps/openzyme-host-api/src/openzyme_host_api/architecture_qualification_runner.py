from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Mapping
from typing import Sequence

from .architecture_qualification import ArchitectureQualificationReportError
from .architecture_qualification import CollectedQualificationScenario
from .architecture_qualification import LoadedArchitectureQualificationReport
from .architecture_qualification import ValidatedInvariantRegistry
from .architecture_qualification import build_architecture_qualification_report
from .architecture_qualification import build_test_manifest
from .architecture_qualification import canonical_json_document_bytes
from .architecture_qualification import collect_architecture_source_identity
from .architecture_qualification import load_invariant_registry
from .architecture_qualification import publish_architecture_qualification_report
from .architecture_qualification import verify_architecture_qualification_report


COLLECTION_SCHEMA_ID = "openzyme_v3_architecture_pytest_collection@1"
EXECUTION_SCHEMA_ID = "openzyme_v3_architecture_pytest_execution@1"
TEST_ROOT = Path("apps/openzyme-host-api/tests/architecture_qualification")
SCENARIO_ROOT = TEST_ROOT / "scenarios"
_COLLECTION_OUTPUT_ENV = "OPENZYME_ARCHITECTURE_COLLECTION_OUTPUT"
_EXECUTION_OUTPUT_ENV = "OPENZYME_ARCHITECTURE_EXECUTION_OUTPUT"
_SENSITIVE_ENV_PARTS = (
    "API_KEY",
    "AUTH_TOKEN",
    "CREDENTIAL",
    "PASSWORD",
    "PRIVATE_KEY",
    "SECRET",
)
_LIVE_ENV_PARTS = (
    "LIVE_E2E",
    "LIVE_HPC",
    "LIVE_LLM",
    "LIVE_TAVILY",
    "RUN_AOX",
    "RUN_LIVE",
)


@dataclass(frozen=True, slots=True)
class CommandExecution:
    command: tuple[str, ...]
    duration_milliseconds: int
    exit_code: int | None
    outcome: str
    stderr_digest: str
    stdout_digest: str


@dataclass(frozen=True, slots=True)
class QualificationRunResult:
    report: LoadedArchitectureQualificationReport
    report_path: Path
    process_exit_code: int


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def non_live_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if source is None else source)
    for key in tuple(environment):
        upper = key.upper()
        if (
            key in {_COLLECTION_OUTPUT_ENV, _EXECUTION_OUTPUT_ENV, "PYTEST_ADDOPTS"}
            or any(part in upper for part in _SENSITIVE_ENV_PARTS)
            or any(part in upper for part in _LIVE_ENV_PARTS)
            or upper in {"SSH_AUTH_SOCK", "SSH_AGENT_PID"}
        ):
            environment.pop(key, None)
    environment.update(
        {
            "OPENZYME_ARCHITECTURE_QUALIFICATION": "1",
            "OPENZYME_LOAD_ENV_FILES": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def _execute(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> tuple[CommandExecution, bytes, bytes]:
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        error = str(exc).encode("utf-8", errors="replace")
        return (
            CommandExecution(
                command=tuple(command),
                duration_milliseconds=0,
                exit_code=None,
                outcome="error",
                stderr_digest=_sha256(error),
                stdout_digest=_sha256(b""),
            ),
            b"",
            error,
        )
    outcome = "error"
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        outcome = "timeout"
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
    else:
        if process.returncode == 0:
            outcome = "pass"
        elif process.returncode == 1:
            outcome = "fail"
        else:
            outcome = "error"
    duration = max(0, round((time.monotonic() - started) * 1000))
    return (
        CommandExecution(
            command=tuple(command),
            duration_milliseconds=duration,
            exit_code=process.returncode,
            outcome=outcome,
            stderr_digest=_sha256(stderr),
            stdout_digest=_sha256(stdout),
        ),
        stdout,
        stderr,
    )


def _load_canonical_object(path: Path, *, schema_id: str) -> dict[str, object]:
    try:
        content = path.read_bytes()

        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result

        payload = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite value {value}")
            ),
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ArchitectureQualificationReportError(
            "qualification pytest evidence is not strict JSON"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_id") != schema_id
        or content != canonical_json_document_bytes(payload)
    ):
        raise ArchitectureQualificationReportError(
            "qualification pytest evidence is not canonical or has the wrong schema"
        )
    return payload


def _collect_manifest(
    *,
    repo_root: Path,
    temporary_root: Path,
    environment: Mapping[str, str],
    registry: ValidatedInvariantRegistry,
) -> tuple[object, CommandExecution]:
    output = temporary_root / "collection.json"
    command = (
        sys.executable,
        "-m",
        "pytest",
        SCENARIO_ROOT.as_posix(),
        "--collect-only",
        "--rootdir=.",
        "-q",
        "-p",
        "no:cacheprovider",
    )
    collection_environment = dict(environment)
    collection_environment[_COLLECTION_OUTPUT_ENV] = str(output)
    execution, _, _ = _execute(
        command,
        cwd=repo_root,
        environment=collection_environment,
        timeout_seconds=60.0,
    )
    if execution.outcome != "pass" or not output.is_file():
        raise ArchitectureQualificationReportError(
            "qualification pytest collection closure failed"
        )
    payload = _load_canonical_object(output, schema_id=COLLECTION_SCHEMA_ID)
    if set(payload) != {"scenarios", "schema_id"} or not isinstance(
        payload["scenarios"], list
    ):
        raise ArchitectureQualificationReportError(
            "qualification pytest collection payload is not closed"
        )
    collected: list[CollectedQualificationScenario] = []
    for raw in payload["scenarios"]:
        if not isinstance(raw, dict) or set(raw) != {
            "family",
            "node_id",
            "scenario_id",
            "selections",
            "source_file",
        }:
            raise ArchitectureQualificationReportError(
                "qualification pytest collection scenario is not closed"
            )
        if not isinstance(raw["selections"], list):
            raise ArchitectureQualificationReportError(
                "qualification pytest collection selections are invalid"
            )
        collected.append(
            CollectedQualificationScenario(
                scenario_id=str(raw["scenario_id"]),
                family=str(raw["family"]),
                node_id=str(raw["node_id"]),
                source_file=str(raw["source_file"]),
                selections=tuple(str(item) for item in raw["selections"]),
            )
        )
    return (
        build_test_manifest(
            registry,
            collected_scenarios=tuple(collected),
            repo_root=repo_root,
        ),
        execution,
    )


def _run_harness_self_tests(
    *,
    repo_root: Path,
    environment: Mapping[str, str],
) -> CommandExecution:
    command = (
        sys.executable,
        "-m",
        "pytest",
        TEST_ROOT.as_posix(),
        f"--ignore={SCENARIO_ROOT.as_posix()}",
        "--rootdir=.",
        "-q",
        "-p",
        "no:cacheprovider",
    )
    execution, _, _ = _execute(
        command,
        cwd=repo_root,
        environment=environment,
        timeout_seconds=180.0,
    )
    return execution


def _fallback_scenario_result(
    *,
    scenario: Mapping[str, object],
    execution: CommandExecution,
) -> dict[str, object]:
    failure_digests = sorted(
        {execution.stdout_digest, execution.stderr_digest} - {_sha256(b"")}
    )
    return {
        "duration_milliseconds": execution.duration_milliseconds,
        "effect_ledger_digests": [],
        "external_effects_real": False,
        "failure_digests": failure_digests,
        "family": scenario["family"],
        "observation_digests": [],
        "observed_p0_trigger_ids": [],
        "pytest_outcome": (
            "timeout" if execution.outcome == "timeout" else "error"
        ),
        "scenario_id": scenario["scenario_id"],
        "test_selector": scenario["test_selector"],
    }


def _run_scenario(
    *,
    repo_root: Path,
    temporary_root: Path,
    environment: Mapping[str, str],
    scenario: Mapping[str, object],
) -> dict[str, object]:
    scenario_id = str(scenario["scenario_id"])
    output = temporary_root / f"execution-{scenario_id}.json"
    command = (
        sys.executable,
        "-m",
        "pytest",
        str(scenario["test_selector"]),
        "--rootdir=.",
        "-q",
        "-p",
        "no:cacheprovider",
    )
    execution_environment = dict(environment)
    execution_environment[_EXECUTION_OUTPUT_ENV] = str(output)
    budgets = scenario["budgets"]
    if not isinstance(budgets, Mapping):
        raise ArchitectureQualificationReportError(
            "registered scenario budgets are invalid"
        )
    execution, _, _ = _execute(
        command,
        cwd=repo_root,
        environment=execution_environment,
        timeout_seconds=float(budgets["deadline_seconds"]) + 15.0,
    )
    if execution.outcome == "timeout" or not output.is_file():
        return _fallback_scenario_result(scenario=scenario, execution=execution)
    try:
        payload = _load_canonical_object(output, schema_id=EXECUTION_SCHEMA_ID)
    except ArchitectureQualificationReportError:
        return _fallback_scenario_result(scenario=scenario, execution=execution)
    if set(payload) != {"records", "schema_id"} or not isinstance(
        payload["records"], list
    ) or len(payload["records"]) != 1:
        return _fallback_scenario_result(scenario=scenario, execution=execution)
    record = payload["records"][0]
    if not isinstance(record, dict) or set(record) != {
        "duration_milliseconds",
        "effect_ledger_digests",
        "external_effects_real",
        "failure_digests",
        "family",
        "observation_digests",
        "observed_p0_trigger_ids",
        "pytest_outcome",
        "scenario_id",
        "test_selector",
    }:
        return _fallback_scenario_result(scenario=scenario, execution=execution)
    expected_process_outcome = {
        "error": "error",
        "fail": "fail",
        "pass": "pass",
        "skip": "pass",
        "xfail": "pass",
        "xpass": "fail",
    }.get(str(record["pytest_outcome"]), "error")
    if (
        record["scenario_id"] != scenario_id
        or record["family"] != scenario["family"]
        or record["test_selector"] != scenario["test_selector"]
        or execution.outcome != expected_process_outcome
    ):
        return _fallback_scenario_result(scenario=scenario, execution=execution)
    return dict(record)


def run_qualification(
    *,
    repo_root: Path,
    runner_path: Path,
    mode: str,
    output_directory: Path,
    command: Sequence[str],
) -> QualificationRunResult:
    root = repo_root.resolve(strict=True)
    registry = load_invariant_registry(repo_root=root)
    environment = non_live_environment()
    with tempfile.TemporaryDirectory(prefix="openzyme-architecture-qualification-") as raw:
        temporary_root = Path(raw)
        test_manifest, collection_execution = _collect_manifest(
            repo_root=root,
            temporary_root=temporary_root,
            environment=environment,
            registry=registry,
        )
        harness_execution = _run_harness_self_tests(
            repo_root=root,
            environment=environment,
        )
        harness_result = {
            "duration_milliseconds": (
                collection_execution.duration_milliseconds
                + harness_execution.duration_milliseconds
            ),
            "exit_code": harness_execution.exit_code,
            "outcome": harness_execution.outcome,
            "stderr_digest": _sha256(
                (
                    collection_execution.stderr_digest
                    + harness_execution.stderr_digest
                ).encode("ascii")
            ),
            "stdout_digest": _sha256(
                (
                    collection_execution.stdout_digest
                    + harness_execution.stdout_digest
                ).encode("ascii")
            ),
        }
        selection_id = "premerge_subset" if mode == "premerge_subset" else "full"
        raw_scenarios = registry.payload["scenarios"]
        if not isinstance(raw_scenarios, list):
            raise ArchitectureQualificationReportError(
                "validated registry scenarios lost list identity"
            )
        selected = [
            item
            for item in raw_scenarios
            if isinstance(item, Mapping) and selection_id in item["selections"]
        ]
        scenario_results = [
            _run_scenario(
                repo_root=root,
                temporary_root=temporary_root,
                environment=environment,
                scenario=scenario,
            )
            for scenario in selected
        ]
    source_identity = collect_architecture_source_identity(repo_root=root)
    report = build_architecture_qualification_report(
        repo_root=root,
        runner_path=runner_path,
        mode=mode,
        command=command,
        registry=registry,
        test_manifest=test_manifest,
        source_identity=source_identity,
        harness_result=harness_result,
        scenario_results=scenario_results,
    )
    report_path = publish_architecture_qualification_report(
        report,
        output_directory=output_directory,
        repo_root=root,
    )
    verification = verify_architecture_qualification_report(
        report_path,
        repo_root=root,
        runner_path=runner_path,
    )
    payload = report.payload
    qualification_green = (
        payload["harness"]["outcome"] == "pass"  # type: ignore[index]
        and all(
            item["qualification_status"] == "satisfied"
            for item in payload["scenario_results"]  # type: ignore[union-attr]
        )
        and all(
            item["status"] == "satisfied"
            for item in payload["invariants"]  # type: ignore[union-attr]
        )
        and not payload["p0_records"]
        and payload["external_effects_real"] is False
        and payload["aox_live_started"] is False
    )
    process_exit_code = (
        0
        if verification.admission_eligible
        or (mode != "admission" and qualification_green)
        else 1
    )
    return QualificationRunResult(
        report=report,
        report_path=report_path,
        process_exit_code=process_exit_code,
    )


__all__ = [
    "CommandExecution",
    "QualificationRunResult",
    "non_live_environment",
    "run_qualification",
]
