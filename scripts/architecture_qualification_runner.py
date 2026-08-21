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
import stat
import sys
import tempfile
from typing import Iterator
from typing import Mapping
from typing import Sequence

from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationError,
)
from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationOutputError,
)
from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationReportError,
)
from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationRunActiveError,
)
from openzyme_host_api.architecture_qualification import ArchitectureQualificationRunError
from openzyme_host_api.architecture_qualification import CollectedQualificationScenario
from openzyme_host_api.architecture_qualification import (
    LoadedArchitectureQualificationReport,
)
from openzyme_host_api.architecture_qualification import ValidatedInvariantRegistry
from openzyme_host_api.architecture_qualification import (
    build_architecture_qualification_report,
)
from openzyme_host_api.architecture_qualification import build_test_manifest
from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_api.architecture_qualification import canonical_json_document_bytes
from openzyme_host_api.architecture_qualification import (
    collect_architecture_qualification_implementation_identity,
)
from openzyme_host_api.architecture_qualification import (
    collect_architecture_source_identity,
)
from openzyme_host_api.architecture_qualification import load_invariant_registry
from openzyme_host_api.architecture_qualification import (
    publish_architecture_qualification_report,
)
from openzyme_host_api.architecture_qualification import (
    validate_architecture_qualification_output_target,
)
from openzyme_host_api.architecture_qualification import (
    verify_architecture_qualification_report,
)

from scripts.test_gate.runner import ProcessResult
from scripts.test_gate.runner import run_command


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
    error: str | None
    kill_sent: bool
    stderr_bytes: int
    stderr_digest: str
    stderr_tail: str
    stdout_bytes: int
    stdout_digest: str
    stdout_tail: str
    term_sent: bool
    timed_out: bool


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
    qualification_tests = str(
        Path(__file__).resolve().parents[1] / "apps/openzyme-host-api/tests"
    )
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        qualification_tests
        if not existing_pythonpath
        else qualification_tests + os.pathsep + existing_pythonpath
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
) -> CommandExecution:
    """Execute only through the repository test-gate process owner."""

    result: ProcessResult = run_command(
        command,
        cwd=cwd,
        environment=environment,
        timeout_seconds=timeout_seconds,
        termination_grace_seconds=5.0,
        tail_bytes=4096,
    )
    return CommandExecution(
        command=result.argv,
        duration_milliseconds=max(0, round(result.duration_ns / 1_000_000)),
        error=result.error,
        exit_code=result.exit_code,
        kill_sent=result.kill_sent,
        outcome=result.outcome,
        stderr_bytes=result.stderr.total_bytes,
        stderr_digest=result.stderr.digest,
        stderr_tail=result.stderr.tail,
        stdout_bytes=result.stdout.total_bytes,
        stdout_digest=result.stdout.digest,
        stdout_tail=result.stdout.tail,
        term_sent=result.term_sent,
        timed_out=result.timed_out,
    )


def _source_digest(source_identity: Mapping[str, object]) -> str:
    return _sha256(canonical_json_bytes(source_identity))


def _revalidate_source(
    *,
    repo_root: Path,
    admission_source: Mapping[str, object],
    phase_id: str,
) -> tuple[Mapping[str, object], dict[str, object]]:
    observed = collect_architecture_source_identity(repo_root=repo_root)
    matched = dict(observed) == dict(admission_source)
    return observed, {
        "matched_admission": matched,
        "phase_id": phase_id,
        "source_identity_digest": _source_digest(observed),
    }


def _safe_process_text(
    value: str,
    *,
    repo_root: Path,
    temporary_root: Path,
) -> str:
    return value.replace(str(temporary_root), "<qualification-temp>").replace(
        str(repo_root),
        "<repo>",
    )


def _process_receipt(
    *,
    execution: CommandExecution,
    phase_id: str,
    scenario_id: str | None,
    source_identity_digest: str,
    repo_root: Path,
    temporary_root: Path,
) -> dict[str, object]:
    preimage: dict[str, object] = {
        "command": [
            _safe_process_text(
                item,
                repo_root=repo_root,
                temporary_root=temporary_root,
            )
            for item in execution.command
        ],
        "duration_milliseconds": execution.duration_milliseconds,
        "error_code": (
            None if execution.error is None else "qualification_process_spawn_failed"
        ),
        "exit_code": execution.exit_code,
        "kill_sent": execution.kill_sent,
        "outcome": execution.outcome,
        "phase_id": phase_id,
        "scenario_id": scenario_id,
        "schema_id": "openzyme_v3_qualification_process_receipt@1",
        "source_identity_digest": source_identity_digest,
        "stderr": {
            "digest": execution.stderr_digest,
            "tail": _safe_process_text(
                execution.stderr_tail,
                repo_root=repo_root,
                temporary_root=temporary_root,
            ),
            "total_bytes": execution.stderr_bytes,
        },
        "stdout": {
            "digest": execution.stdout_digest,
            "tail": _safe_process_text(
                execution.stdout_tail,
                repo_root=repo_root,
                temporary_root=temporary_root,
            ),
            "total_bytes": execution.stdout_bytes,
        },
        "term_sent": execution.term_sent,
        "timed_out": execution.timed_out,
    }
    return {
        **preimage,
        "receipt_digest": _sha256(canonical_json_bytes(preimage)),
    }


def _run_failure(
    *,
    cause_id: str,
    phase_id: str,
    source_identity: Mapping[str, object],
    process_receipt: Mapping[str, object] | None = None,
    scenario_id: str | None = None,
) -> dict[str, object]:
    return {
        "cause_id": cause_id,
        "phase_id": phase_id,
        "process_receipt_digest": (
            None
            if process_receipt is None
            else str(process_receipt["receipt_digest"])
        ),
        "scenario_id": scenario_id,
        "source_identity_digest": _source_digest(source_identity),
    }


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
    declared_manifest: object,
) -> tuple[object, CommandExecution, bool]:
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
        "architecture_qualification.no_live_effects",
        "-p",
        "no:cacheprovider",
    )
    collection_environment = dict(environment)
    collection_environment[_COLLECTION_OUTPUT_ENV] = str(output)
    execution = _execute(
        command,
        cwd=repo_root,
        environment=collection_environment,
        timeout_seconds=60.0,
    )
    try:
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
        collected_manifest = build_test_manifest(
            registry,
            collected_scenarios=tuple(collected),
            repo_root=repo_root,
        )
        if collected_manifest != declared_manifest:
            raise ArchitectureQualificationReportError(
                "qualification pytest collection differs from the declared manifest"
            )
    except ArchitectureQualificationReportError:
        return declared_manifest, execution, False
    return collected_manifest, execution, True


def _declared_manifest(
    *,
    registry: ValidatedInvariantRegistry,
    repo_root: Path,
) -> object:
    raw_scenarios = registry.payload["scenarios"]
    if not isinstance(raw_scenarios, list):
        raise ArchitectureQualificationReportError(
            "validated registry scenarios lost list identity"
        )
    collected = tuple(
        CollectedQualificationScenario(
            scenario_id=str(item["scenario_id"]),
            family=str(item["family"]),
            node_id=str(item["test_selector"]),
            source_file=str(item["source_files"][0]),
            selections=tuple(str(value) for value in item["selections"]),
        )
        for item in raw_scenarios
        if isinstance(item, Mapping)
        and isinstance(item.get("source_files"), list)
        and len(item["source_files"]) == 1
    )
    if len(collected) != len(raw_scenarios):
        raise ArchitectureQualificationReportError(
            "declared qualification manifest is not reconstructable"
        )
    return build_test_manifest(
        registry,
        collected_scenarios=collected,
        repo_root=repo_root,
    )


def _run_harness_self_tests(
    *,
    repo_root: Path,
    environment: Mapping[str, str],
    node_output: Path | None = None,
) -> tuple[CommandExecution, list[dict[str, object]], bool]:
    command = (
        sys.executable,
        "-m",
        "pytest",
        TEST_ROOT.as_posix(),
        f"--ignore={SCENARIO_ROOT.as_posix()}",
        "--rootdir=.",
        "-q",
        "-p",
        "architecture_qualification.no_live_effects",
        "-p",
        "no:cacheprovider",
    )
    execution_environment = dict(environment)
    if node_output is not None:
        execution_environment[_MAINLINE_NODE_OUTPUT_ENV] = str(node_output)
    execution = _execute(
        command,
        cwd=repo_root,
        environment=execution_environment,
        timeout_seconds=180.0,
    )
    if node_output is None:
        return execution, [], execution.outcome == "pass"
    if not node_output.is_file():
        return execution, [], False
    try:
        records = _load_mainline_node_records(node_output)
    except ArchitectureQualificationReportError:
        return execution, [], False
    return execution, records, execution.outcome == "pass" and bool(records)


def _run_scenario(
    *,
    repo_root: Path,
    temporary_root: Path,
    environment: Mapping[str, str],
    scenario: Mapping[str, object],
    node_output: Path | None = None,
) -> tuple[dict[str, object] | None, list[dict[str, object]], CommandExecution]:
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
        "architecture_qualification.no_live_effects",
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
    execution = _execute(
        command,
        cwd=repo_root,
        environment=execution_environment,
        timeout_seconds=float(budgets["deadline_seconds"]) + 15.0,
    )
    node_records: list[dict[str, object]] = []
    if node_output is not None and node_output.is_file():
        try:
            node_records = _load_mainline_node_records(node_output)
        except ArchitectureQualificationReportError:
            return None, [], execution
    if execution.outcome == "timeout" or not output.is_file():
        return None, node_records, execution
    try:
        payload = _load_canonical_object(output, schema_id=EXECUTION_SCHEMA_ID)
    except ArchitectureQualificationReportError:
        return None, node_records, execution
    if set(payload) != {"records", "schema_id"} or not isinstance(
        payload["records"], list
    ) or len(payload["records"]) != 1:
        return None, node_records, execution
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
        return None, node_records, execution
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
        return None, node_records, execution
    if node_output is not None and [
        str(item["node_id"]) for item in node_records
    ] != [str(scenario["test_selector"])]:
        return None, [], execution
    return dict(record), node_records, execution


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
        and payload.get("live_campaign_started") is False
        and payload.get("run_failure") is None
        and payload.get("not_run_scenario_ids") == []
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
    admission_source: Mapping[str, object],
    mainline_sidecar: MainlineQualificationSidecarRequest | None = None,
) -> QualificationRunResult:
    root = repo_root
    registry = load_invariant_registry(repo_root=root)
    test_manifest = _declared_manifest(registry=registry, repo_root=root)
    implementation_identity = (
        collect_architecture_qualification_implementation_identity(
            repo_root=root,
            runner_path=runner_path,
            test_manifest=test_manifest,
        )
    )
    environment = non_live_environment()
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
    selected_ids = [str(item["scenario_id"]) for item in selected]
    admission_source_digest = _source_digest(admission_source)
    source_revalidations: list[dict[str, object]] = [
        {
            "matched_admission": True,
            "phase_id": "lock_admission",
            "source_identity_digest": admission_source_digest,
        }
    ]
    process_receipts: list[dict[str, object]] = []
    run_failure: dict[str, object] | None = None
    scenario_results: list[dict[str, object]] = []
    harness_node_records: list[dict[str, object]] = []
    scenario_node_records: list[dict[str, object]] = []
    empty_digest = _sha256(b"")
    harness_result: dict[str, object] = {
        "duration_milliseconds": 0,
        "exit_code": None,
        "outcome": "error",
        "stderr_digest": empty_digest,
        "stdout_digest": empty_digest,
    }
    terminal_source: Mapping[str, object] = admission_source
    with tempfile.TemporaryDirectory(prefix="openzyme-architecture-qualification-") as raw:
        temporary_root = Path(raw)
        observed, revalidation = _revalidate_source(
            repo_root=root,
            admission_source=admission_source,
            phase_id="before_collection",
        )
        source_revalidations.append(revalidation)
        terminal_source = observed
        if revalidation["matched_admission"] is not True:
            run_failure = _run_failure(
                cause_id="architecture_qualification_source_drift",
                phase_id="before_collection",
                source_identity=observed,
            )

        collection_execution: CommandExecution | None = None
        if run_failure is None:
            test_manifest, collection_execution, collection_closed = _collect_manifest(
                repo_root=root,
                temporary_root=temporary_root,
                environment=environment,
                registry=registry,
                declared_manifest=test_manifest,
            )
            collection_receipt = _process_receipt(
                execution=collection_execution,
                phase_id="collection",
                scenario_id=None,
                source_identity_digest=admission_source_digest,
                repo_root=root,
                temporary_root=temporary_root,
            )
            process_receipts.append(collection_receipt)
            harness_result = {
                "duration_milliseconds": collection_execution.duration_milliseconds,
                "exit_code": collection_execution.exit_code,
                "outcome": collection_execution.outcome,
                "stderr_digest": collection_execution.stderr_digest,
                "stdout_digest": collection_execution.stdout_digest,
            }
            if not collection_closed:
                run_failure = _run_failure(
                    cause_id="architecture_qualification_collection_failed",
                    phase_id="collection",
                    source_identity=admission_source,
                    process_receipt=collection_receipt,
                )

        if collection_execution is not None:
            observed, revalidation = _revalidate_source(
                repo_root=root,
                admission_source=admission_source,
                phase_id="after_collection",
            )
            source_revalidations.append(revalidation)
            terminal_source = observed
            if run_failure is None and revalidation["matched_admission"] is not True:
                run_failure = _run_failure(
                    cause_id="architecture_qualification_source_drift",
                    phase_id="after_collection",
                    source_identity=observed,
                )

        if run_failure is None:
            harness_execution, harness_node_records, harness_closed = (
                _run_harness_self_tests(
                    repo_root=root,
                    environment=environment,
                    node_output=(
                        None
                        if mainline_sidecar is None
                        else temporary_root / "mainline-harness-nodes.json"
                    ),
                )
            )
            harness_receipt = _process_receipt(
                execution=harness_execution,
                phase_id="harness",
                scenario_id=None,
                source_identity_digest=admission_source_digest,
                repo_root=root,
                temporary_root=temporary_root,
            )
            process_receipts.append(harness_receipt)
            assert collection_execution is not None
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
            if not harness_closed:
                run_failure = _run_failure(
                    cause_id="architecture_qualification_harness_failed",
                    phase_id="harness",
                    source_identity=admission_source,
                    process_receipt=harness_receipt,
                )

        if len(process_receipts) >= 2:
            observed, revalidation = _revalidate_source(
                repo_root=root,
                admission_source=admission_source,
                phase_id="after_harness",
            )
            source_revalidations.append(revalidation)
            terminal_source = observed
            if run_failure is None and revalidation["matched_admission"] is not True:
                run_failure = _run_failure(
                    cause_id="architecture_qualification_source_drift",
                    phase_id="after_harness",
                    source_identity=observed,
                )

        for scenario in selected:
            if run_failure is not None:
                break
            scenario_id = str(scenario["scenario_id"])
            observed, revalidation = _revalidate_source(
                repo_root=root,
                admission_source=admission_source,
                phase_id=f"before_scenario:{scenario_id}",
            )
            source_revalidations.append(revalidation)
            terminal_source = observed
            if revalidation["matched_admission"] is not True:
                run_failure = _run_failure(
                    cause_id="architecture_qualification_source_drift",
                    phase_id=f"before_scenario:{scenario_id}",
                    scenario_id=scenario_id,
                    source_identity=observed,
                )
                break
            result, node_records, scenario_execution = _run_scenario(
                repo_root=root,
                temporary_root=temporary_root,
                environment=environment,
                scenario=scenario,
                node_output=(
                    None
                    if mainline_sidecar is None
                    else temporary_root / f"mainline-scenario-{scenario_id}.json"
                ),
            )
            scenario_receipt = _process_receipt(
                execution=scenario_execution,
                phase_id=f"scenario:{scenario_id}",
                scenario_id=scenario_id,
                source_identity_digest=admission_source_digest,
                repo_root=root,
                temporary_root=temporary_root,
            )
            process_receipts.append(scenario_receipt)
            if result is None:
                run_failure = _run_failure(
                    cause_id="architecture_qualification_scenario_execution_failed",
                    phase_id=f"scenario:{scenario_id}",
                    scenario_id=scenario_id,
                    source_identity=admission_source,
                    process_receipt=scenario_receipt,
                )
                break
            scenario_results.append(result)
            scenario_node_records.extend(node_records)
            observed, revalidation = _revalidate_source(
                repo_root=root,
                admission_source=admission_source,
                phase_id=f"after_scenario:{scenario_id}",
            )
            source_revalidations.append(revalidation)
            terminal_source = observed
            if revalidation["matched_admission"] is not True:
                run_failure = _run_failure(
                    cause_id="architecture_qualification_source_drift",
                    phase_id=f"after_scenario:{scenario_id}",
                    scenario_id=scenario_id,
                    source_identity=observed,
                )
                break

        observed, revalidation = _revalidate_source(
            repo_root=root,
            admission_source=admission_source,
            phase_id="pre_publication",
        )
        source_revalidations.append(revalidation)
        terminal_source = observed
        if run_failure is None and revalidation["matched_admission"] is not True:
            run_failure = _run_failure(
                cause_id="architecture_qualification_source_drift",
                phase_id="pre_publication",
                source_identity=observed,
            )

    completed_scenario_ids = {str(item["scenario_id"]) for item in scenario_results}
    not_run_scenario_ids = sorted(set(selected_ids) - completed_scenario_ids)
    report = build_architecture_qualification_report(
        repo_root=root,
        runner_path=runner_path,
        mode=mode,
        command=command,
        registry=registry,
        test_manifest=test_manifest,
        source_identity=admission_source,
        terminal_source_identity=terminal_source,
        source_revalidations=source_revalidations,
        process_receipts=process_receipts,
        run_failure=run_failure,
        not_run_scenario_ids=not_run_scenario_ids,
        harness_result=harness_result,
        scenario_results=scenario_results,
        implementation_identity=implementation_identity,
    )
    report_path = publish_architecture_qualification_report(
        report,
        output_directory=output_directory,
        repo_root=root,
    )
    try:
        verification = verify_architecture_qualification_report(
            report_path,
            repo_root=root,
            runner_path=runner_path,
        )
    except ArchitectureQualificationError:
        verification = None
    payload = report.payload
    qualification_green = _qualification_evidence_is_green(payload)
    process_exit_code = (
        0
        if verification is not None and verification.admission_eligible
        or (mode != "admission" and qualification_green)
        else 1
    )
    sidecar_path = (
        None
        if mainline_sidecar is None or run_failure is not None or verification is None
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
        admission_source = collect_architecture_source_identity(repo_root=root)
        return _run_qualification_locked(
            repo_root=root,
            runner_path=runner_path,
            mode=mode,
            output_directory=output_directory,
            command=command,
            admission_source=admission_source,
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
