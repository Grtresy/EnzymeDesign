from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Iterator
from typing import Mapping
from typing import Sequence

from .architecture_qualification import ArchitectureQualificationOutputError
from .architecture_qualification import ArchitectureQualificationReportError
from .architecture_qualification import ArchitectureQualificationRunActiveError
from .architecture_qualification import ArchitectureQualificationRunError
from .architecture_qualification import CollectedQualificationScenario
from .architecture_qualification import LoadedArchitectureQualificationReport
from .architecture_qualification import ValidatedInvariantRegistry
from .architecture_qualification import build_architecture_qualification_report
from .architecture_qualification import build_test_manifest
from .architecture_qualification import canonical_json_bytes
from .architecture_qualification import canonical_json_document_bytes
from .architecture_qualification import collect_architecture_source_identity
from .architecture_qualification import load_invariant_registry
from .architecture_qualification import publish_architecture_qualification_report
from .architecture_qualification import (
    validate_architecture_qualification_output_target,
)
from .architecture_qualification import verify_architecture_qualification_report


COLLECTION_SCHEMA_ID = "openzyme_v3_architecture_pytest_collection@1"
EXECUTION_SCHEMA_ID = "openzyme_v3_architecture_pytest_execution@1"
MAINLINE_NODE_SCHEMA_ID = "openzyme_v3_mainline_qualification_pytest@1"
MAINLINE_SIDECAR_SCHEMA_ID = "openzyme_test_qualification_execution@1"
TEST_ROOT = Path("apps/openzyme-host-api/tests/architecture_qualification")
SCENARIO_ROOT = TEST_ROOT / "scenarios"
_COLLECTION_OUTPUT_ENV = "OPENZYME_ARCHITECTURE_COLLECTION_OUTPUT"
_EXECUTION_OUTPUT_ENV = "OPENZYME_ARCHITECTURE_EXECUTION_OUTPUT"
MAINLINE_SIDECAR_OUTPUT_ENV = "OPENZYME_MAINLINE_QUALIFICATION_SIDECAR"
MAINLINE_INVOCATION_ID_ENV = "OPENZYME_MAINLINE_INVOCATION_ID"
MAINLINE_PLAN_DIGEST_ENV = "OPENZYME_MAINLINE_PLAN_DIGEST"
MAINLINE_SOURCE_DIGEST_ENV = "OPENZYME_MAINLINE_SOURCE_DIGEST"
MAINLINE_ENVIRONMENT_DIGEST_ENV = "OPENZYME_MAINLINE_ENVIRONMENT_DIGEST"
_MAINLINE_NODE_OUTPUT_ENV = "OPENZYME_MAINLINE_QUALIFICATION_NODE_OUTPUT"
_MAINLINE_REQUEST_ENV_KEYS = frozenset(
    {
        MAINLINE_SIDECAR_OUTPUT_ENV,
        MAINLINE_INVOCATION_ID_ENV,
        MAINLINE_PLAN_DIGEST_ENV,
        MAINLINE_SOURCE_DIGEST_ENV,
        MAINLINE_ENVIRONMENT_DIGEST_ENV,
        _MAINLINE_NODE_OUTPUT_ENV,
    }
)
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
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
_QUALIFICATION_LOCK_ROOT_NAME = "openzyme-v3-architecture-qualification-locks"
_QUALIFICATION_MODES = frozenset(
    {"admission", "diagnostic", "premerge_subset"}
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
    mainline_sidecar_path: Path | None = None


@dataclass(frozen=True, slots=True)
class MainlineQualificationSidecarRequest:
    output_path: Path
    invocation_id: str
    plan_digest: str
    source_identity_digest: str
    environment_digest: str


def _secure_qualification_lock_root() -> Path:
    try:
        temporary_root = Path("/tmp").resolve(strict=True)
    except OSError as exc:
        raise ArchitectureQualificationRunError(
            "qualification single-flight root is unavailable"
        ) from exc
    if not temporary_root.is_dir():
        raise ArchitectureQualificationRunError(
            "qualification single-flight root is not a directory"
        )
    lock_root = temporary_root / f"{_QUALIFICATION_LOCK_ROOT_NAME}-{os.getuid()}"
    try:
        os.mkdir(lock_root, mode=0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise ArchitectureQualificationRunError(
            "qualification single-flight directory could not be created"
        ) from exc
    try:
        lock_root_stat = os.lstat(lock_root)
    except OSError as exc:
        raise ArchitectureQualificationRunError(
            "qualification single-flight directory is unavailable"
        ) from exc
    lock_root_mode = stat.S_IMODE(lock_root_stat.st_mode)
    if (
        not stat.S_ISDIR(lock_root_stat.st_mode)
        or lock_root_stat.st_uid != os.getuid()
        or lock_root_mode & 0o700 != 0o700
        or lock_root_mode & 0o077
    ):
        raise ArchitectureQualificationRunError(
            "qualification single-flight directory is not private and canonical"
        )
    return lock_root


def _qualification_lock_path(repo_root: Path) -> Path:
    try:
        canonical_root = repo_root.resolve(strict=True)
        root_stat = canonical_root.stat()
    except OSError as exc:
        raise ArchitectureQualificationRunError(
            "qualification checkout identity is unavailable"
        ) from exc
    if not canonical_root.is_dir():
        raise ArchitectureQualificationRunError(
            "qualification checkout identity is not a directory"
        )
    identity = f"{root_stat.st_dev}:{root_stat.st_ino}".encode("ascii")
    return _secure_qualification_lock_root() / f"{hashlib.sha256(identity).hexdigest()}.lock"


@contextmanager
def _qualification_single_flight(repo_root: Path) -> Iterator[None]:
    lock_path = _qualification_lock_path(repo_root)
    required_flags = ("O_CLOEXEC", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required_flags):
        raise ArchitectureQualificationRunError(
            "qualification single-flight requires no-follow close-on-exec locks"
        )
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ArchitectureQualificationRunError(
            "qualification single-flight lock is unavailable"
        ) from exc
    try:
        opened_stat = os.fstat(descriptor)
        opened_mode = stat.S_IMODE(opened_stat.st_mode)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_uid != os.getuid()
            or opened_stat.st_nlink != 1
            or opened_mode & 0o600 != 0o600
            or opened_mode & 0o077
        ):
            raise ArchitectureQualificationRunError(
                "qualification single-flight lock is not private and canonical"
            )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ArchitectureQualificationRunActiveError(
                "architecture qualification is already active for this checkout"
            ) from exc
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise ArchitectureQualificationRunActiveError(
                    "architecture qualification is already active for this checkout"
                ) from exc
            raise ArchitectureQualificationRunError(
                "qualification single-flight lock could not be acquired"
            ) from exc
        try:
            named_stat = os.lstat(lock_path)
        except OSError as exc:
            raise ArchitectureQualificationRunError(
                "qualification single-flight lock identity disappeared"
            ) from exc
        if (
            named_stat.st_dev != opened_stat.st_dev
            or named_stat.st_ino != opened_stat.st_ino
            or not stat.S_ISREG(named_stat.st_mode)
        ):
            raise ArchitectureQualificationRunError(
                "qualification single-flight lock identity drifted"
            )
        yield
    finally:
        os.close(descriptor)


def _validate_mainline_sidecar_output_target(
    *,
    repo_root: Path,
    request: MainlineQualificationSidecarRequest,
) -> Path:
    output_path = request.output_path
    if not output_path.is_absolute():
        raise ArchitectureQualificationOutputError(
            "mainline qualification sidecar path must be absolute"
        )
    if Path(os.path.normpath(str(output_path))) != output_path:
        raise ArchitectureQualificationOutputError(
            "mainline qualification sidecar path must be lexically canonical"
        )
    if output_path.exists() or output_path.is_symlink():
        raise ArchitectureQualificationOutputError(
            "mainline qualification sidecar already exists"
        )
    try:
        root = repo_root.resolve(strict=True)
        parent = output_path.parent.resolve(strict=True)
    except OSError as exc:
        raise ArchitectureQualificationOutputError(
            "mainline qualification sidecar parent is unavailable"
        ) from exc
    if output_path.parent.absolute() != parent or not parent.is_dir():
        raise ArchitectureQualificationOutputError(
            "mainline qualification sidecar parent aliases another directory"
        )
    candidate = parent / output_path.name
    try:
        candidate.relative_to(root)
    except ValueError:
        pass
    else:
        raise ArchitectureQualificationOutputError(
            "mainline qualification sidecar must be outside the checkout"
        )
    return candidate


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def non_live_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if source is None else source)
    for key in tuple(environment):
        upper = key.upper()
        if (
            key
            in {
                _COLLECTION_OUTPUT_ENV,
                _EXECUTION_OUTPUT_ENV,
                "PYTEST_ADDOPTS",
                *_MAINLINE_REQUEST_ENV_KEYS,
            }
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


def mainline_sidecar_request_from_environment(
    source: Mapping[str, str] | None = None,
) -> MainlineQualificationSidecarRequest | None:
    """Parse the optional all-or-nothing private mainline sidecar binding."""

    environment = os.environ if source is None else source
    values = {
        key: environment.get(key)
        for key in (
            MAINLINE_SIDECAR_OUTPUT_ENV,
            MAINLINE_INVOCATION_ID_ENV,
            MAINLINE_PLAN_DIGEST_ENV,
            MAINLINE_SOURCE_DIGEST_ENV,
            MAINLINE_ENVIRONMENT_DIGEST_ENV,
        )
    }
    present = {key for key, value in values.items() if value is not None}
    if not present:
        return None
    if present != set(values):
        missing = sorted(set(values) - present)
        raise ArchitectureQualificationReportError(
            "mainline qualification sidecar binding is incomplete: "
            + ", ".join(missing)
        )
    output_text = values[MAINLINE_SIDECAR_OUTPUT_ENV]
    invocation_id = values[MAINLINE_INVOCATION_ID_ENV]
    if not isinstance(output_text, str) or not output_text:
        raise ArchitectureQualificationOutputError(
            "mainline qualification sidecar output path is invalid"
        )
    output_path = Path(output_text)
    if not output_path.is_absolute():
        raise ArchitectureQualificationOutputError(
            "mainline qualification sidecar output path must be absolute"
        )
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ArchitectureQualificationReportError(
            "mainline qualification invocation id is invalid"
        )
    digests: dict[str, str] = {}
    for key in (
        MAINLINE_PLAN_DIGEST_ENV,
        MAINLINE_SOURCE_DIGEST_ENV,
        MAINLINE_ENVIRONMENT_DIGEST_ENV,
    ):
        value = values[key]
        if (
            not isinstance(value, str)
            or _DIGEST_PATTERN.fullmatch(value) is None
        ):
            raise ArchitectureQualificationReportError(
                f"mainline qualification binding {key} is invalid"
            )
        digests[key] = value
    return MainlineQualificationSidecarRequest(
        output_path=output_path,
        invocation_id=invocation_id,
        plan_digest=digests[MAINLINE_PLAN_DIGEST_ENV],
        source_identity_digest=digests[MAINLINE_SOURCE_DIGEST_ENV],
        environment_digest=digests[MAINLINE_ENVIRONMENT_DIGEST_ENV],
    )


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


def _load_mainline_node_records(path: Path) -> list[dict[str, object]]:
    payload = _load_canonical_object(path, schema_id=MAINLINE_NODE_SCHEMA_ID)
    if set(payload) != {"nodes", "schema_id"} or not isinstance(
        payload["nodes"], list
    ):
        raise ArchitectureQualificationReportError(
            "mainline qualification node payload is not closed"
        )
    records: list[dict[str, object]] = []
    for index, raw in enumerate(payload["nodes"]):
        if not isinstance(raw, dict) or set(raw) != {
            "duration_ns",
            "markers",
            "node_id",
            "outcome",
            "phases",
        }:
            raise ArchitectureQualificationReportError(
                f"mainline qualification node record {index} is not closed"
            )
        node_id = raw["node_id"]
        markers = raw["markers"]
        outcome = raw["outcome"]
        duration_ns = raw["duration_ns"]
        phases = raw["phases"]
        if (
            not isinstance(node_id, str)
            or not node_id
            or not isinstance(markers, list)
            or any(not isinstance(marker, str) or not marker for marker in markers)
            or markers != sorted(set(markers))
            or outcome
            not in {"pass", "fail", "skip", "xfail", "xpass", "error"}
            or type(duration_ns) is not int
            or duration_ns < 0
            or not isinstance(phases, list)
        ):
            raise ArchitectureQualificationReportError(
                f"mainline qualification node record {index} is invalid"
            )
        records.append(dict(raw))
    node_ids = [str(item["node_id"]) for item in records]
    if node_ids != sorted(set(node_ids)):
        raise ArchitectureQualificationReportError(
            "mainline qualification node ids are not sorted and unique"
        )
    return records


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
    node_output: Path | None = None,
) -> tuple[CommandExecution, list[dict[str, object]]]:
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
    execution_environment = dict(environment)
    if node_output is not None:
        execution_environment[_MAINLINE_NODE_OUTPUT_ENV] = str(node_output)
    execution, _, _ = _execute(
        command,
        cwd=repo_root,
        environment=execution_environment,
        timeout_seconds=180.0,
    )
    if node_output is None:
        return execution, []
    if not node_output.is_file():
        raise ArchitectureQualificationReportError(
            "mainline qualification harness node evidence is missing"
        )
    return execution, _load_mainline_node_records(node_output)


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
    node_output: Path | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
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
    if node_output is not None:
        execution_environment[_MAINLINE_NODE_OUTPUT_ENV] = str(node_output)
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
    if node_output is None:
        node_records: list[dict[str, object]] = []
    elif not node_output.is_file():
        raise ArchitectureQualificationReportError(
            f"mainline qualification scenario node evidence is missing: {scenario_id}"
        )
    else:
        node_records = _load_mainline_node_records(node_output)
    if execution.outcome == "timeout" or not output.is_file():
        return (
            _fallback_scenario_result(scenario=scenario, execution=execution),
            node_records,
        )
    try:
        payload = _load_canonical_object(output, schema_id=EXECUTION_SCHEMA_ID)
    except ArchitectureQualificationReportError:
        return (
            _fallback_scenario_result(scenario=scenario, execution=execution),
            node_records,
        )
    if set(payload) != {"records", "schema_id"} or not isinstance(
        payload["records"], list
    ) or len(payload["records"]) != 1:
        return (
            _fallback_scenario_result(scenario=scenario, execution=execution),
            node_records,
        )
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
        return (
            _fallback_scenario_result(scenario=scenario, execution=execution),
            node_records,
        )
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
        return (
            _fallback_scenario_result(scenario=scenario, execution=execution),
            node_records,
        )
    return dict(record), node_records


def _qualification_evidence_is_green(payload: Mapping[str, object]) -> bool:
    harness = payload.get("harness")
    scenario_results = payload.get("scenario_results")
    invariants = payload.get("invariants")
    p0_records = payload.get("p0_records")
    if (
        not isinstance(harness, Mapping)
        or not isinstance(scenario_results, list)
        or not isinstance(invariants, list)
        or not isinstance(p0_records, list)
    ):
        return False
    return (
        harness.get("outcome") == "pass"
        and all(
            isinstance(item, Mapping)
            and item.get("qualification_status") == "satisfied"
            for item in scenario_results
        )
        and all(
            isinstance(item, Mapping) and item.get("status") == "satisfied"
            for item in invariants
        )
        and all(
            isinstance(item, Mapping) and item.get("status") == "closed"
            for item in p0_records
        )
        and payload.get("external_effects_real") is False
        and payload.get("aox_live_started") is False
    )


def _publish_mainline_sidecar(
    *,
    repo_root: Path,
    request: MainlineQualificationSidecarRequest,
    mode: str,
    report_path: Path,
    report_payload_digest: str,
    harness_records: Sequence[Mapping[str, object]],
    scenario_records: Sequence[Mapping[str, object]],
) -> Path:
    output_path = _validate_mainline_sidecar_output_target(
        repo_root=repo_root,
        request=request,
    )
    parent = output_path.parent
    harness = [dict(item) for item in harness_records]
    scenarios = [dict(item) for item in scenario_records]
    harness.sort(key=lambda item: str(item["node_id"]))
    scenarios.sort(key=lambda item: str(item["node_id"]))
    node_results = sorted(
        [*harness, *scenarios],
        key=lambda item: str(item["node_id"]),
    )
    node_ids = [str(item["node_id"]) for item in node_results]
    if node_ids != sorted(set(node_ids)):
        raise ArchitectureQualificationReportError(
            "mainline qualification sidecar node ids overlap or duplicate"
        )
    fields: dict[str, object] = {
        "schema_id": MAINLINE_SIDECAR_SCHEMA_ID,
        "invocation_id": request.invocation_id,
        "plan_digest": request.plan_digest,
        "source_identity_digest": request.source_identity_digest,
        "environment_digest": request.environment_digest,
        "qualification_report_digest": report_payload_digest,
        "qualification_report_path": str(report_path),
        "node_results": node_results,
        "harness_collection": [
            {
                "markers": item["markers"],
                "node_id": item["node_id"],
            }
            for item in harness
        ],
        "scenario_collection": [
            {
                "markers": item["markers"],
                "node_id": item["node_id"],
            }
            for item in scenarios
        ],
        "qualification_mode": mode,
    }
    fields["self_digest"] = _sha256(canonical_json_bytes(fields))
    content = canonical_json_document_bytes(fields)
    try:
        with output_path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ArchitectureQualificationOutputError(
            "mainline qualification sidecar already exists"
        ) from exc
    try:
        directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise ArchitectureQualificationOutputError(
            "mainline qualification sidecar parent sync failed"
        ) from exc
    return output_path


def _run_qualification_locked(
    *,
    repo_root: Path,
    runner_path: Path,
    mode: str,
    output_directory: Path,
    command: Sequence[str],
    mainline_sidecar: MainlineQualificationSidecarRequest | None = None,
) -> QualificationRunResult:
    root = repo_root
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
        harness_execution, harness_node_records = _run_harness_self_tests(
            repo_root=root,
            environment=environment,
            node_output=(
                None
                if mainline_sidecar is None
                else temporary_root / "mainline-harness-nodes.json"
            ),
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
        scenario_pairs = [
            _run_scenario(
                repo_root=root,
                temporary_root=temporary_root,
                environment=environment,
                scenario=scenario,
                node_output=(
                    None
                    if mainline_sidecar is None
                    else temporary_root
                    / f"mainline-scenario-{scenario['scenario_id']}.json"
                ),
            )
            for scenario in selected
        ]
        scenario_results = [result for result, _ in scenario_pairs]
        scenario_node_records = [
            node
            for _, records in scenario_pairs
            for node in records
        ]
        if mainline_sidecar is not None:
            harness_ids = [
                str(item["node_id"]) for item in harness_node_records
            ]
            scenario_ids = [
                str(item["node_id"]) for item in scenario_node_records
            ]
            expected_scenario_ids = sorted(
                str(item["test_selector"]) for item in selected
            )
            if harness_ids != sorted(set(harness_ids)) or not harness_ids:
                raise ArchitectureQualificationReportError(
                    "mainline qualification harness node closure failed"
                )
            if sorted(scenario_ids) != expected_scenario_ids:
                raise ArchitectureQualificationReportError(
                    "mainline qualification scenario node closure failed"
                )
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
    qualification_green = _qualification_evidence_is_green(payload)
    process_exit_code = (
        0
        if verification.admission_eligible
        or (mode != "admission" and qualification_green)
        else 1
    )
    sidecar_path = (
        None
        if mainline_sidecar is None
        else _publish_mainline_sidecar(
            repo_root=root,
            request=mainline_sidecar,
            mode=mode,
            report_path=report_path,
            report_payload_digest=report.payload_digest,
            harness_records=harness_node_records,
            scenario_records=scenario_node_records,
        )
    )
    return QualificationRunResult(
        report=report,
        report_path=report_path,
        process_exit_code=process_exit_code,
        mainline_sidecar_path=sidecar_path,
    )


def run_qualification(
    *,
    repo_root: Path,
    runner_path: Path,
    mode: str,
    output_directory: Path,
    command: Sequence[str],
    mainline_sidecar: MainlineQualificationSidecarRequest | None = None,
) -> QualificationRunResult:
    if mode not in _QUALIFICATION_MODES:
        raise ArchitectureQualificationRunError(
            "architecture qualification mode is invalid"
        )
    validated_output = validate_architecture_qualification_output_target(
        output_directory=output_directory,
        repo_root=repo_root,
    )
    root = validated_output.repo_root
    if mainline_sidecar is not None:
        _validate_mainline_sidecar_output_target(
            repo_root=root,
            request=mainline_sidecar,
        )
    with _qualification_single_flight(root):
        validate_architecture_qualification_output_target(
            output_directory=output_directory,
            repo_root=root,
        )
        if mainline_sidecar is not None:
            _validate_mainline_sidecar_output_target(
                repo_root=root,
                request=mainline_sidecar,
            )
        return _run_qualification_locked(
            repo_root=root,
            runner_path=runner_path,
            mode=mode,
            output_directory=output_directory,
            command=command,
            mainline_sidecar=mainline_sidecar,
        )


__all__ = [
    "CommandExecution",
    "MainlineQualificationSidecarRequest",
    "QualificationRunResult",
    "mainline_sidecar_request_from_environment",
    "non_live_environment",
    "run_qualification",
]
