from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import subprocess
from typing import Any

from .architecture_qualification import ArchitectureQualificationReportError
from .architecture_qualification import ArchitectureQualificationVerification
from .architecture_qualification import CollectedQualificationScenario
from .architecture_qualification import LoadedArchitectureQualificationReport
from .architecture_qualification import PROFILE_ID
from .architecture_qualification import QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID
from .architecture_qualification import QUALIFICATION_REPORT_SCHEMA_ID
from .architecture_qualification import ValidatedInvariantRegistry
from .architecture_qualification import ValidatedTestManifest
from .architecture_qualification import build_test_manifest
from .architecture_qualification import canonical_json_bytes
from .architecture_qualification import canonical_json_document_bytes
from .architecture_qualification import load_invariant_registry


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_CHANGE_REF = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_MODES = frozenset({"admission", "diagnostic", "premerge_subset"})
P0_CLOSURE_SCHEMA_ID = "openzyme_v3_architecture_p0_closures@1"
P0_CLOSURE_RELATIVE_PATH = Path(
    "docs/v3/architecture-qualification/p0-closures.json"
)
_PYTEST_OUTCOMES = frozenset(
    {"error", "fail", "pass", "skip", "timeout", "xfail", "xpass"}
)
_QUALIFICATION_STATUSES = frozenset({"satisfied", "unproven", "violated"})
_GAP_CLASSIFICATIONS = frozenset(
    {
        "declared_profile_limitation",
        "deferred_enhancement",
        "product_defect",
        "qualification_defect",
    }
)
_REPORT_FIELDS = frozenset({"payload", "payload_digest", "schema_id"})
_PAYLOAD_FIELDS = frozenset(
    {
        "admission_eligible",
        "aox_live_started",
        "command",
        "external_effects_real",
        "gaps",
        "harness",
        "implementation",
        "invariants",
        "mode",
        "p0_records",
        "payload_schema_id",
        "profile",
        "registry_digest",
        "rejection_reasons",
        "scenario_results",
        "selection",
        "source_identity",
        "test_manifest",
        "test_manifest_digest",
    }
)
_SOURCE_FIELDS = frozenset(
    {
        "commit",
        "repo_root",
        "tracked_diff_digest",
        "tracked_dirty_paths",
        "untracked_manifest_digest",
        "untracked_sources",
        "worktree_clean",
    }
)
_FILE_FIELDS = frozenset({"byte_length", "content_digest", "path"})
_DIGESTED_FILE_FIELDS = frozenset({"content_digest", "path"})
_PROFILE_FIELDS = frozenset({"claims", "excludes", "profile_id"})
_SELECTION_FIELDS = frozenset({"scenario_ids", "selection_id"})
_HARNESS_FIELDS = frozenset(
    {
        "duration_milliseconds",
        "exit_code",
        "outcome",
        "stderr_digest",
        "stdout_digest",
    }
)
_IDENTITY_FIELDS = frozenset(
    {"files", "implementation_digest", "runner", "verifier"}
)
_VERIFIER_FIELDS = frozenset({"content_digest", "files"})
_SCENARIO_RESULT_FIELDS = frozenset(
    {
        "budget_exceeded",
        "budgets",
        "duration_milliseconds",
        "effect_ledger_digests",
        "execution_ledger_digest",
        "external_effects_real",
        "failure_digests",
        "family",
        "observation_digests",
        "observed_p0_trigger_ids",
        "pytest_outcome",
        "qualification_status",
        "scenario_id",
        "test_selector",
    }
)
_BUDGET_FIELDS = frozenset(
    {
        "deadline_seconds",
        "max_effect_count",
        "max_event_delta",
        "max_state_version_delta",
        "max_steps",
        "max_ticks",
    }
)
_INVARIANT_RESULT_FIELDS = frozenset(
    {"evidence_digest", "family", "invariant_id", "scenario_ids", "status"}
)
_GAP_FIELDS = frozenset(
    {
        "classification",
        "evidence_digest",
        "gap_id",
        "invariant_id",
        "owner",
        "priority_recommendation",
        "profile_id",
        "related_change_ref",
        "reproducer",
        "trigger_ids",
    }
)
_P0_FIELDS = frozenset(
    {
        "change_ref",
        "closure_commit",
        "invariant_id",
        "p0_id",
        "status",
        "trigger_ids",
    }
)
_P0_CLOSURE_FIELDS = frozenset({"records", "schema_id"})
_P0_CLOSURE_RECORD_FIELDS = frozenset(
    set(_P0_FIELDS) | {"baseline_report_payload_digest", "red_scenario_id"}
)
_TEST_MANIFEST_FIELDS = frozenset(
    {
        "contract_files",
        "implementation_files",
        "registry_digest",
        "scenarios",
        "schema_id",
    }
)
_TEST_MANIFEST_SCENARIO_FIELDS = frozenset(
    {
        "collected_node_id",
        "family",
        "scenario_id",
        "selections",
        "source_files",
    }
)


def _error(message: str) -> ArchitectureQualificationReportError:
    return ArchitectureQualificationReportError(message)


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _value_digest(value: object) -> str:
    return _sha256(canonical_json_bytes(value))


def _object(value: object, *, fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise _error(f"{label} is not a closed object")
    return value


def _list(value: object, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise _error(f"{label} must be a list")
    return value


def _text(value: object, *, label: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise _error(f"{label} must be text")
    return value


def _digest(value: object, *, label: str) -> str:
    text = _text(value, label=label)
    if _DIGEST.fullmatch(text) is None:
        raise _error(f"{label} must be a sha256 digest")
    return text


def _boolean(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise _error(f"{label} must be boolean")
    return value


def _nonnegative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _error(f"{label} must be a non-negative integer")
    return value


def _optional_int(value: object, *, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(f"{label} must be an integer or null")
    return value


def _optional_text(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label=label)


def _texts(
    value: object,
    *,
    label: str,
    sorted_unique: bool = True,
) -> list[str]:
    items = _list(value, label=label)
    if any(not isinstance(item, str) or not item for item in items):
        raise _error(f"{label} must contain non-empty text")
    result = [str(item) for item in items]
    if sorted_unique and result != sorted(set(result)):
        raise _error(f"{label} must be sorted and unique")
    return result


def _digests(value: object, *, label: str) -> list[str]:
    values = _texts(value, label=label)
    for index, item in enumerate(values):
        _digest(item, label=f"{label}[{index}]")
    return values


def _relative_source_path(value: object, *, label: str) -> str:
    text = _text(value, label=label)
    path = PurePosixPath(text)
    if path.is_absolute() or text != path.as_posix() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise _error(f"{label} must be a normalized repository-relative path")
    return text


def _validate_digested_file(value: object, *, label: str) -> dict[str, Any]:
    item = _object(value, fields=_DIGESTED_FILE_FIELDS, label=label)
    _relative_source_path(item["path"], label=f"{label}.path")
    _digest(item["content_digest"], label=f"{label}.content_digest")
    return item


def _validate_file(value: object, *, label: str) -> dict[str, Any]:
    item = _object(value, fields=_FILE_FIELDS, label=label)
    _relative_source_path(item["path"], label=f"{label}.path")
    _digest(item["content_digest"], label=f"{label}.content_digest")
    _nonnegative_int(item["byte_length"], label=f"{label}.byte_length")
    return item


def _validate_sorted_records(
    records: list[dict[str, Any]],
    *,
    key: str,
    label: str,
) -> None:
    values = [str(item[key]) for item in records]
    if values != sorted(set(values)):
        raise _error(f"{label} must be sorted and unique by {key}")


def _strict_json(content: bytes) -> object:
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _error("qualification report is not strict UTF-8") from exc

    def reject_constant(value: str) -> None:
        raise _error(f"qualification report contains non-finite constant {value}")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _error(f"qualification report contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except ArchitectureQualificationReportError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _error("qualification report is not strict JSON") from exc


def _run_git(repo_root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _error("qualification source identity could not execute git") from exc
    if completed.returncode != 0:
        raise _error("qualification source identity git command failed")
    return completed.stdout


def _canonical_repo_root(repo_root: Path) -> Path:
    try:
        requested = repo_root.resolve(strict=True)
    except OSError as exc:
        raise _error("qualification repository root is unavailable") from exc
    try:
        declared = Path(
            _run_git(requested, "rev-parse", "--show-toplevel")
            .decode("utf-8", errors="strict")
            .strip()
        ).resolve(strict=True)
    except (OSError, UnicodeDecodeError) as exc:
        raise _error("git returned an invalid canonical repository root") from exc
    if requested != declared or not requested.is_dir():
        raise _error("qualification must use the canonical repository root")
    return requested


def _split_nul(content: bytes, *, label: str) -> list[str]:
    if not content:
        return []
    raw_items = content.split(b"\0")
    if raw_items[-1] == b"":
        raw_items.pop()
    try:
        return [item.decode("utf-8", errors="strict") for item in raw_items]
    except UnicodeDecodeError as exc:
        raise _error(f"{label} contains a non-UTF-8 path") from exc


def collect_source_identity(*, repo_root: Path) -> Mapping[str, object]:
    root = _canonical_repo_root(repo_root)
    try:
        commit = _run_git(root, "rev-parse", "HEAD").decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise _error("git HEAD is not ASCII") from exc
    if _COMMIT.fullmatch(commit) is None:
        raise _error("git HEAD must be a full lowercase commit")

    tracked_diff = _run_git(root, "diff", "--binary", "--no-ext-diff", "HEAD", "--")
    tracked_paths = sorted(
        set(
            _split_nul(
                _run_git(root, "diff", "--name-only", "-z", "HEAD", "--"),
                label="tracked source manifest",
            )
        )
    )
    for index, path in enumerate(tracked_paths):
        _relative_source_path(path, label=f"tracked_dirty_paths[{index}]")

    untracked_paths = sorted(
        set(
            _split_nul(
                _run_git(root, "ls-files", "--others", "--exclude-standard", "-z"),
                label="untracked source manifest",
            )
        )
    )
    untracked_sources: list[dict[str, object]] = []
    for index, raw_path in enumerate(untracked_paths):
        normalized = _relative_source_path(
            raw_path,
            label=f"untracked_sources[{index}].path",
        )
        candidate = root / normalized
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise _error("an untracked source escapes or is unreadable") from exc
        if candidate.is_symlink() or not resolved.is_file() or relative.as_posix() != normalized:
            raise _error("untracked source identity requires regular non-alias files")
        content = resolved.read_bytes()
        untracked_sources.append(
            {
                "byte_length": len(content),
                "content_digest": _sha256(content),
                "path": normalized,
            }
        )
    return {
        "commit": commit,
        "repo_root": str(root),
        "tracked_diff_digest": _sha256(tracked_diff),
        "tracked_dirty_paths": tracked_paths,
        "untracked_manifest_digest": _value_digest(untracked_sources),
        "untracked_sources": untracked_sources,
        "worktree_clean": not tracked_diff and not untracked_sources,
    }


def _relative_file_entry(path: Path, *, repo_root: Path) -> dict[str, str]:
    root = _canonical_repo_root(repo_root)
    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise _error("qualification implementation file is outside the repository") from exc
    if path.is_symlink() or not resolved.is_file():
        raise _error("qualification implementation identity requires a regular file")
    return {
        "content_digest": _sha256(resolved.read_bytes()),
        "path": relative.as_posix(),
    }


def _implementation_identity(
    *,
    repo_root: Path,
    runner_path: Path,
    test_manifest: Mapping[str, object],
) -> dict[str, object]:
    root = _canonical_repo_root(repo_root)
    files = _list(test_manifest.get("implementation_files"), label="implementation files")
    validated_files = [
        dict(_validate_digested_file(item, label=f"implementation files[{index}]"))
        for index, item in enumerate(files)
    ]
    if [item["path"] for item in validated_files] != sorted(
        {str(item["path"]) for item in validated_files}
    ):
        raise _error("implementation files must be sorted and unique")
    runner = _relative_file_entry(runner_path, repo_root=root)
    package_root = Path(__file__).resolve().parent
    verifier_files = sorted(
        [
            _relative_file_entry(
                package_root / "architecture_qualification.py",
                repo_root=root,
            ),
            _relative_file_entry(Path(__file__), repo_root=root),
        ],
        key=lambda item: item["path"],
    )
    return {
        "files": validated_files,
        "implementation_digest": _value_digest(validated_files),
        "runner": runner,
        "verifier": {
            "content_digest": _value_digest(verifier_files),
            "files": verifier_files,
        },
    }


def _registry_records(
    registry: ValidatedInvariantRegistry,
) -> tuple[dict[str, Mapping[str, object]], dict[str, Mapping[str, object]]]:
    raw_scenarios = _list(registry.payload.get("scenarios"), label="registry scenarios")
    raw_invariants = _list(
        registry.payload.get("invariants"), label="registry invariants"
    )
    scenarios = {
        str(item["scenario_id"]): item
        for item in raw_scenarios
        if isinstance(item, Mapping)
    }
    invariants = {
        str(item["invariant_id"]): item
        for item in raw_invariants
        if isinstance(item, Mapping)
    }
    if len(scenarios) != len(raw_scenarios) or len(invariants) != len(raw_invariants):
        raise _error("validated registry records lost object identity")
    return scenarios, invariants


def _closure_commit_is_ancestor(*, repo_root: Path, commit: str) -> bool:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "merge-base",
                "--is-ancestor",
                commit,
                "HEAD",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _error("P0 closure commit ancestry could not be verified") from exc
    if completed.returncode == 0:
        return True
    return False


def _load_p0_closure_records(
    *,
    repo_root: Path,
    registry: ValidatedInvariantRegistry,
) -> list[dict[str, object]]:
    path = repo_root / P0_CLOSURE_RELATIVE_PATH
    if path.is_symlink() or not path.is_file():
        raise _error("P0 closure registry must be a regular non-symlink file")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise _error("P0 closure registry is unreadable") from exc
    raw_payload = _strict_json(content)
    payload = _object(
        raw_payload,
        fields=_P0_CLOSURE_FIELDS,
        label="P0 closure registry",
    )
    if content != canonical_json_document_bytes(payload):
        raise _error("P0 closure registry is not canonical JSON followed by one LF")
    if payload["schema_id"] != P0_CLOSURE_SCHEMA_ID:
        raise _error("P0 closure registry schema is unsupported")

    scenarios, invariants = _registry_records(registry)
    report_records: list[dict[str, object]] = []
    for index, raw_record in enumerate(
        _list(payload["records"], label="P0 closure records")
    ):
        record = _object(
            raw_record,
            fields=_P0_CLOSURE_RECORD_FIELDS,
            label=f"P0 closure records[{index}]",
        )
        _digest(
            record["baseline_report_payload_digest"],
            label=f"P0 closure records[{index}].baseline report payload digest",
        )
        red_scenario_id = _text(
            record["red_scenario_id"],
            label=f"P0 closure records[{index}].red scenario id",
        )
        report_record = {
            key: record[key] for key in sorted(_P0_FIELDS)
        }
        _validate_p0(report_record, index=index)
        if report_record["status"] != "closed":
            raise _error("P0 closure registry may contain only closed records")
        invariant_id = str(report_record["invariant_id"])
        invariant = invariants.get(invariant_id)
        if invariant is None:
            raise _error("P0 closure registry references an unknown invariant")
        if report_record["p0_id"] != f"p0.{invariant_id}":
            raise _error("P0 closure registry P0 identity drifted")
        if red_scenario_id not in invariant["scenario_ids"]:
            raise _error("P0 closure registry red scenario is not owned by its invariant")
        if red_scenario_id not in scenarios:
            raise _error("P0 closure registry red scenario is unknown")
        trigger_ids = set(report_record["trigger_ids"])
        if not trigger_ids or not trigger_ids <= set(invariant["p0_trigger_ids"]):
            raise _error("P0 closure registry trigger identity drifted")
        change_ref = str(report_record["change_ref"])
        if _CHANGE_REF.fullmatch(change_ref) is None:
            raise _error("P0 closure registry change ref is invalid")
        closure_commit = str(report_record["closure_commit"])
        if not _closure_commit_is_ancestor(
            repo_root=repo_root,
            commit=closure_commit,
        ):
            raise _error("P0 closure commit is not an ancestor of current HEAD")
        report_records.append(report_record)
    _validate_sorted_records(
        report_records,
        key="p0_id",
        label="P0 closure records",
    )
    return report_records


def _selection(
    *,
    mode: str,
    registry: ValidatedInvariantRegistry,
) -> dict[str, object]:
    selection_id = "premerge_subset" if mode == "premerge_subset" else "full"
    scenarios, _ = _registry_records(registry)
    scenario_ids = sorted(
        scenario_id
        for scenario_id, record in scenarios.items()
        if selection_id in record["selections"]
    )
    return {"scenario_ids": scenario_ids, "selection_id": selection_id}


def _execution_facts(result: Mapping[str, object]) -> dict[str, object]:
    return {
        "duration_milliseconds": result["duration_milliseconds"],
        "effect_ledger_digests": result["effect_ledger_digests"],
        "external_effects_real": result["external_effects_real"],
        "failure_digests": result["failure_digests"],
        "family": result["family"],
        "observation_digests": result["observation_digests"],
        "observed_p0_trigger_ids": result["observed_p0_trigger_ids"],
        "pytest_outcome": result["pytest_outcome"],
        "scenario_id": result["scenario_id"],
        "test_selector": result["test_selector"],
    }


def _scenario_status(
    facts: Mapping[str, object],
    *,
    deadline_seconds: int,
) -> tuple[str, bool]:
    duration = int(facts["duration_milliseconds"])
    exceeded = duration > deadline_seconds * 1000
    outcome = str(facts["pytest_outcome"])
    observations = facts["observation_digests"]
    effects = facts["effect_ledger_digests"]
    if bool(facts["external_effects_real"]):
        return "violated", exceeded
    if exceeded or outcome in {"error", "skip", "timeout", "xfail", "xpass"}:
        return "unproven", exceeded
    if outcome == "fail":
        return ("violated" if observations and effects else "unproven"), exceeded
    if outcome == "pass" and observations and effects:
        return "satisfied", exceeded
    return "unproven", exceeded


def _normalize_scenario_results(
    raw_results: Sequence[Mapping[str, object]],
    *,
    registry: ValidatedInvariantRegistry,
    selection: Mapping[str, object],
) -> list[dict[str, object]]:
    scenarios, _ = _registry_records(registry)
    selected_ids = list(selection["scenario_ids"])
    by_id: dict[str, Mapping[str, object]] = {}
    for raw in raw_results:
        scenario_id = str(raw.get("scenario_id") or "")
        if scenario_id in by_id:
            raise _error(f"scenario result {scenario_id!r} is duplicated")
        by_id[scenario_id] = raw
    if sorted(by_id) != selected_ids:
        raise _error("scenario results do not equal the exact selected scenario set")

    normalized: list[dict[str, object]] = []
    for scenario_id in selected_ids:
        raw = by_id[scenario_id]
        expected = scenarios[scenario_id]
        outcome = _text(raw.get("pytest_outcome"), label="pytest outcome")
        if outcome not in _PYTEST_OUTCOMES:
            raise _error(f"scenario {scenario_id!r} has an unknown pytest outcome")
        duration = _nonnegative_int(
            raw.get("duration_milliseconds"), label="scenario duration"
        )
        family = _text(raw.get("family"), label="scenario family")
        selector = _text(raw.get("test_selector"), label="scenario selector")
        if family != expected["family"] or selector != expected["test_selector"]:
            raise _error(f"scenario {scenario_id!r} identity drifted")
        observations = _digests(
            raw.get("observation_digests"), label="scenario observation digests"
        )
        effects = _digests(
            raw.get("effect_ledger_digests"), label="scenario effect ledger digests"
        )
        failures = _digests(
            raw.get("failure_digests"), label="scenario failure digests"
        )
        external_effects_real = _boolean(
            raw.get("external_effects_real"), label="scenario external effect flag"
        )
        budgets = dict(expected["budgets"])
        observed_triggers = _texts(
            raw.get("observed_p0_trigger_ids"),
            label="scenario observed P0 trigger ids",
        )
        _, invariants = _registry_records(registry)
        allowed_triggers = {
            str(trigger_id)
            for invariant in invariants.values()
            if scenario_id in invariant["scenario_ids"]
            for trigger_id in invariant["p0_trigger_ids"]
        }
        if not set(observed_triggers) <= allowed_triggers:
            raise _error(
                f"scenario {scenario_id!r} recorded an undeclared P0 trigger"
            )
        if outcome == "pass" and observed_triggers:
            raise _error(
                f"satisfied scenario {scenario_id!r} cannot record a P0 trigger"
            )
        facts = {
            "duration_milliseconds": duration,
            "effect_ledger_digests": effects,
            "external_effects_real": external_effects_real,
            "failure_digests": failures,
            "family": family,
            "observation_digests": observations,
            "observed_p0_trigger_ids": observed_triggers,
            "pytest_outcome": outcome,
            "scenario_id": scenario_id,
            "test_selector": selector,
        }
        status, exceeded = _scenario_status(
            facts,
            deadline_seconds=int(budgets["deadline_seconds"]),
        )
        normalized.append(
            {
                "budget_exceeded": exceeded,
                "budgets": budgets,
                **facts,
                "execution_ledger_digest": _value_digest(facts),
                "qualification_status": status,
            }
        )
    return normalized


def _invariant_results(
    *,
    registry: ValidatedInvariantRegistry,
    scenario_results: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    _, invariants = _registry_records(registry)
    results = {str(item["scenario_id"]): item for item in scenario_results}
    output: list[dict[str, object]] = []
    for invariant_id in sorted(invariants):
        invariant = invariants[invariant_id]
        scenario_ids = [str(item) for item in invariant["scenario_ids"]]
        selected = [results[item] for item in scenario_ids if item in results]
        statuses = [str(item["qualification_status"]) for item in selected]
        if not selected or "unproven" in statuses:
            status = "unproven"
        elif "violated" in statuses:
            status = "violated"
        elif len(selected) == len(scenario_ids) and set(statuses) == {"satisfied"}:
            status = "satisfied"
        else:
            status = "unproven"
        output.append(
            {
                "evidence_digest": _value_digest(selected),
                "family": invariant["family"],
                "invariant_id": invariant_id,
                "scenario_ids": scenario_ids,
                "status": status,
            }
        )
    return output


def _gap_and_p0_records(
    *,
    registry: ValidatedInvariantRegistry,
    invariant_results: Sequence[Mapping[str, object]],
    scenario_results: Sequence[Mapping[str, object]],
    closed_p0_records: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    scenarios, invariants = _registry_records(registry)
    scenario_evidence = {
        str(item["scenario_id"]): item for item in scenario_results
    }
    gaps: list[dict[str, object]] = []
    p0_records: list[dict[str, object]] = []
    for result in invariant_results:
        status = str(result["status"])
        if status == "satisfied":
            continue
        invariant_id = str(result["invariant_id"])
        invariant = invariants[invariant_id]
        permitted_triggers = {str(item) for item in invariant["p0_trigger_ids"]}
        trigger_ids = sorted(
            {
                str(trigger_id)
                for scenario_id in invariant["scenario_ids"]
                if scenario_id in scenario_evidence
                for trigger_id in scenario_evidence[scenario_id][
                    "observed_p0_trigger_ids"
                ]
                if str(trigger_id) in permitted_triggers
            }
            if status == "violated"
            else set()
        )
        priority = "p0" if trigger_ids else "blocking"
        scenario_ids = [str(item) for item in invariant["scenario_ids"]]
        reproducer = str(scenarios[scenario_ids[0]]["test_selector"])
        gap = {
            "classification": (
                "product_defect" if status == "violated" else "qualification_defect"
            ),
            "evidence_digest": result["evidence_digest"],
            "gap_id": f"gap.{invariant_id}",
            "invariant_id": invariant_id,
            "owner": invariant["owner_boundary"],
            "priority_recommendation": priority,
            "profile_id": PROFILE_ID,
            "related_change_ref": None,
            "reproducer": reproducer,
            "trigger_ids": trigger_ids,
        }
        gaps.append(gap)
        if priority == "p0":
            p0_records.append(
                {
                    "change_ref": None,
                    "closure_commit": None,
                    "invariant_id": invariant_id,
                    "p0_id": f"p0.{invariant_id}",
                    "status": "open",
                    "trigger_ids": trigger_ids,
                }
            )
    invariant_status = {
        str(item["invariant_id"]): str(item["status"])
        for item in invariant_results
    }
    open_p0_ids = {str(item["p0_id"]) for item in p0_records}
    for raw_record in closed_p0_records:
        record = dict(raw_record)
        invariant_id = str(record["invariant_id"])
        if (
            invariant_status.get(invariant_id) == "satisfied"
            and str(record["p0_id"]) not in open_p0_ids
        ):
            p0_records.append(record)
    p0_records.sort(key=lambda item: str(item["p0_id"]))
    return gaps, p0_records


def _rejection_and_eligibility(
    *,
    mode: str,
    source_identity: Mapping[str, object],
    selection: Mapping[str, object],
    harness: Mapping[str, object],
    scenario_results: Sequence[Mapping[str, object]],
    invariant_results: Sequence[Mapping[str, object]],
    p0_records: Sequence[Mapping[str, object]],
    external_effects_real: bool,
    aox_live_started: bool,
) -> tuple[list[str], bool]:
    reasons: list[str] = []
    if mode != "admission":
        reasons.append("mode_not_admission")
    if selection["selection_id"] != "full":
        reasons.append("selection_not_full")
    if source_identity["worktree_clean"] is not True:
        reasons.append("source_not_clean")
    if harness["outcome"] != "pass":
        reasons.append("qualification_harness_not_satisfied")
    if any(item["qualification_status"] != "satisfied" for item in scenario_results):
        reasons.append("scenarios_not_satisfied")
    if any(item["status"] != "satisfied" for item in invariant_results):
        reasons.append("invariants_not_satisfied")
    if any(item["status"] == "open" for item in p0_records):
        reasons.append("open_p0")
    if external_effects_real:
        reasons.append("real_external_effect_detected")
    if aox_live_started:
        reasons.append("aox_live_started")
    normalized = sorted(set(reasons))
    return normalized, not normalized


def _profile(registry: ValidatedInvariantRegistry) -> dict[str, object]:
    raw = registry.payload["profile"]
    if not isinstance(raw, Mapping):
        raise _error("validated registry profile lost object identity")
    return {
        "claims": list(raw["claims"]),
        "excludes": list(raw["excludes"]),
        "profile_id": raw["profile_id"],
    }


def build_report(
    *,
    repo_root: Path,
    runner_path: Path,
    mode: str,
    command: Sequence[str],
    registry: ValidatedInvariantRegistry,
    test_manifest: ValidatedTestManifest,
    source_identity: Mapping[str, object],
    harness_result: Mapping[str, object],
    scenario_results: Sequence[Mapping[str, object]],
) -> LoadedArchitectureQualificationReport:
    if mode not in _MODES:
        raise _error("qualification report mode is unknown")
    root = _canonical_repo_root(repo_root)
    current_source = collect_source_identity(repo_root=root)
    if dict(source_identity) != dict(current_source):
        raise _error("source identity changed while the report was assembled")
    harness = _validate_harness(dict(harness_result))
    selection = _selection(mode=mode, registry=registry)
    normalized_scenarios = _normalize_scenario_results(
        scenario_results,
        registry=registry,
        selection=selection,
    )
    invariant_results = _invariant_results(
        registry=registry,
        scenario_results=normalized_scenarios,
    )
    closed_p0_records = _load_p0_closure_records(
        repo_root=root,
        registry=registry,
    )
    gaps, p0_records = _gap_and_p0_records(
        registry=registry,
        invariant_results=invariant_results,
        scenario_results=normalized_scenarios,
        closed_p0_records=closed_p0_records,
    )
    external_effects_real = any(
        bool(item["external_effects_real"]) for item in normalized_scenarios
    )
    aox_live_started = False
    rejection_reasons, admission_eligible = _rejection_and_eligibility(
        mode=mode,
        source_identity=current_source,
        selection=selection,
        harness=harness,
        scenario_results=normalized_scenarios,
        invariant_results=invariant_results,
        p0_records=p0_records,
        external_effects_real=external_effects_real,
        aox_live_started=aox_live_started,
    )
    payload: dict[str, object] = {
        "admission_eligible": admission_eligible,
        "aox_live_started": aox_live_started,
        "command": [str(item) for item in command],
        "external_effects_real": external_effects_real,
        "gaps": gaps,
        "harness": harness,
        "implementation": _implementation_identity(
            repo_root=root,
            runner_path=runner_path,
            test_manifest=test_manifest.payload,
        ),
        "invariants": invariant_results,
        "mode": mode,
        "p0_records": p0_records,
        "payload_schema_id": QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID,
        "profile": _profile(registry),
        "registry_digest": registry.registry_digest,
        "rejection_reasons": rejection_reasons,
        "scenario_results": normalized_scenarios,
        "selection": selection,
        "source_identity": dict(current_source),
        "test_manifest": dict(test_manifest.payload),
        "test_manifest_digest": test_manifest.test_manifest_digest,
    }
    payload_digest = _sha256(canonical_json_bytes(payload))
    envelope = {
        "payload": payload,
        "payload_digest": payload_digest,
        "schema_id": QUALIFICATION_REPORT_SCHEMA_ID,
    }
    return load_report_bytes(canonical_json_document_bytes(envelope))


def _validate_source(value: object) -> dict[str, Any]:
    source = _object(value, fields=_SOURCE_FIELDS, label="source_identity")
    commit = _text(source["commit"], label="source_identity.commit")
    if _COMMIT.fullmatch(commit) is None:
        raise _error("source_identity.commit must be a full lowercase commit")
    root = _text(source["repo_root"], label="source_identity.repo_root")
    if not Path(root).is_absolute():
        raise _error("source_identity.repo_root must be absolute")
    _digest(source["tracked_diff_digest"], label="tracked_diff_digest")
    _texts(source["tracked_dirty_paths"], label="tracked_dirty_paths")
    raw_untracked = _list(source["untracked_sources"], label="untracked_sources")
    untracked = [
        _validate_file(item, label=f"untracked_sources[{index}]")
        for index, item in enumerate(raw_untracked)
    ]
    _validate_sorted_records(untracked, key="path", label="untracked_sources")
    manifest_digest = _digest(
        source["untracked_manifest_digest"], label="untracked_manifest_digest"
    )
    if manifest_digest != _value_digest(untracked):
        raise _error("untracked source manifest digest drifted")
    clean = _boolean(source["worktree_clean"], label="worktree_clean")
    if clean != (
        source["tracked_diff_digest"] == _sha256(b"") and not untracked
    ):
        raise _error("worktree_clean contradicts the bound source identity")
    return source


def _validate_harness(value: object) -> dict[str, Any]:
    harness = _object(value, fields=_HARNESS_FIELDS, label="harness")
    outcome = _text(harness["outcome"], label="harness.outcome")
    if outcome not in {"error", "fail", "pass", "timeout"}:
        raise _error("harness outcome is unknown")
    _optional_int(harness["exit_code"], label="harness.exit_code")
    _nonnegative_int(
        harness["duration_milliseconds"], label="harness.duration_milliseconds"
    )
    _digest(harness["stdout_digest"], label="harness.stdout_digest")
    _digest(harness["stderr_digest"], label="harness.stderr_digest")
    return harness


def _validate_test_manifest(value: object) -> dict[str, Any]:
    manifest = _object(value, fields=_TEST_MANIFEST_FIELDS, label="test_manifest")
    _text(manifest["schema_id"], label="test_manifest.schema_id")
    _digest(manifest["registry_digest"], label="test_manifest.registry_digest")
    for field in ("contract_files", "implementation_files"):
        entries = [
            _validate_digested_file(item, label=f"test_manifest.{field}[{index}]")
            for index, item in enumerate(_list(manifest[field], label=field))
        ]
        _validate_sorted_records(entries, key="path", label=f"test_manifest.{field}")
    scenarios = [
        _object(
            item,
            fields=_TEST_MANIFEST_SCENARIO_FIELDS,
            label=f"test_manifest.scenarios[{index}]",
        )
        for index, item in enumerate(
            _list(manifest["scenarios"], label="test_manifest.scenarios")
        )
    ]
    for index, scenario in enumerate(scenarios):
        _text(scenario["scenario_id"], label=f"manifest scenario {index} id")
        _text(scenario["family"], label=f"manifest scenario {index} family")
        _text(scenario["collected_node_id"], label=f"manifest scenario {index} node")
        _texts(scenario["selections"], label=f"manifest scenario {index} selections")
        sources = [
            _validate_digested_file(item, label=f"manifest scenario {index} source")
            for item in _list(scenario["source_files"], label="manifest sources")
        ]
        _validate_sorted_records(sources, key="path", label="manifest sources")
    _validate_sorted_records(scenarios, key="scenario_id", label="manifest scenarios")
    return manifest


def _validate_implementation(value: object) -> dict[str, Any]:
    identity = _object(value, fields=_IDENTITY_FIELDS, label="implementation")
    files = [
        _validate_digested_file(item, label=f"implementation.files[{index}]")
        for index, item in enumerate(_list(identity["files"], label="implementation.files"))
    ]
    _validate_sorted_records(files, key="path", label="implementation.files")
    if _digest(identity["implementation_digest"], label="implementation digest") != _value_digest(files):
        raise _error("implementation digest drifted")
    _validate_digested_file(identity["runner"], label="implementation.runner")
    verifier = _object(
        identity["verifier"], fields=_VERIFIER_FIELDS, label="implementation.verifier"
    )
    verifier_files = [
        _validate_digested_file(item, label=f"verifier.files[{index}]")
        for index, item in enumerate(_list(verifier["files"], label="verifier.files"))
    ]
    _validate_sorted_records(verifier_files, key="path", label="verifier.files")
    if _digest(verifier["content_digest"], label="verifier content digest") != _value_digest(verifier_files):
        raise _error("verifier content digest drifted")
    return identity


def _validate_scenario_result(value: object, *, index: int) -> dict[str, Any]:
    result = _object(
        value,
        fields=_SCENARIO_RESULT_FIELDS,
        label=f"scenario_results[{index}]",
    )
    _text(result["scenario_id"], label="scenario id")
    _text(result["family"], label="scenario family")
    _text(result["test_selector"], label="scenario selector")
    outcome = _text(result["pytest_outcome"], label="pytest outcome")
    if outcome not in _PYTEST_OUTCOMES:
        raise _error("scenario pytest outcome is unknown")
    status = _text(result["qualification_status"], label="qualification status")
    if status not in _QUALIFICATION_STATUSES:
        raise _error("scenario qualification status is unknown")
    _nonnegative_int(result["duration_milliseconds"], label="scenario duration")
    _boolean(result["budget_exceeded"], label="scenario budget flag")
    _boolean(result["external_effects_real"], label="scenario external effect flag")
    _digests(result["observation_digests"], label="scenario observation digests")
    _digests(result["effect_ledger_digests"], label="scenario effect ledger digests")
    _digests(result["failure_digests"], label="scenario failure digests")
    _texts(
        result["observed_p0_trigger_ids"],
        label="scenario observed P0 trigger ids",
    )
    _digest(result["execution_ledger_digest"], label="execution ledger digest")
    budgets = _object(result["budgets"], fields=_BUDGET_FIELDS, label="scenario budgets")
    for key in sorted(_BUDGET_FIELDS):
        _nonnegative_int(budgets[key], label=f"scenario budgets.{key}")
    return result


def _validate_invariant_result(value: object, *, index: int) -> dict[str, Any]:
    result = _object(
        value,
        fields=_INVARIANT_RESULT_FIELDS,
        label=f"invariants[{index}]",
    )
    _text(result["invariant_id"], label="invariant id")
    _text(result["family"], label="invariant family")
    status = _text(result["status"], label="invariant status")
    if status not in _QUALIFICATION_STATUSES:
        raise _error("invariant status is unknown")
    _texts(result["scenario_ids"], label="invariant scenario ids")
    _digest(result["evidence_digest"], label="invariant evidence digest")
    return result


def _validate_gap(value: object, *, index: int) -> dict[str, Any]:
    gap = _object(value, fields=_GAP_FIELDS, label=f"gaps[{index}]")
    _text(gap["gap_id"], label="gap id")
    _text(gap["invariant_id"], label="gap invariant id")
    classification = _text(gap["classification"], label="gap classification")
    if classification not in _GAP_CLASSIFICATIONS:
        raise _error("gap classification is unknown")
    _text(gap["owner"], label="gap owner")
    _text(gap["reproducer"], label="gap reproducer")
    _digest(gap["evidence_digest"], label="gap evidence digest")
    _text(gap["profile_id"], label="gap profile")
    _optional_text(gap["related_change_ref"], label="gap change ref")
    priority = _text(gap["priority_recommendation"], label="gap priority")
    if priority not in {"blocking", "p0"}:
        raise _error("gap priority recommendation is unknown")
    _texts(gap["trigger_ids"], label="gap trigger ids")
    return gap


def _validate_p0(value: object, *, index: int) -> dict[str, Any]:
    record = _object(value, fields=_P0_FIELDS, label=f"p0_records[{index}]")
    _text(record["p0_id"], label="P0 id")
    _text(record["invariant_id"], label="P0 invariant id")
    status = _text(record["status"], label="P0 status")
    if status not in {"closed", "open"}:
        raise _error("P0 status is unknown")
    change_ref = _optional_text(record["change_ref"], label="P0 change ref")
    closure = _optional_text(record["closure_commit"], label="P0 closure commit")
    if status == "open" and (change_ref is not None or closure is not None):
        raise _error("open P0 cannot claim closure evidence")
    if status == "closed" and (change_ref is None or closure is None):
        raise _error("closed P0 requires change and commit evidence")
    if closure is not None and _COMMIT.fullmatch(closure) is None:
        raise _error("P0 closure commit must be a full lowercase commit")
    _texts(record["trigger_ids"], label="P0 trigger ids")
    return record


def _validate_payload(value: object) -> dict[str, Any]:
    payload = _object(value, fields=_PAYLOAD_FIELDS, label="report payload")
    if payload["payload_schema_id"] != QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID:
        raise _error("qualification payload schema is unsupported")
    mode = _text(payload["mode"], label="report mode")
    if mode not in _MODES:
        raise _error("qualification report mode is unknown")
    command = _texts(payload["command"], label="report command", sorted_unique=False)
    if not command:
        raise _error("report command must not be empty")
    _boolean(payload["admission_eligible"], label="admission eligibility")
    _boolean(payload["aox_live_started"], label="AOX live flag")
    _boolean(payload["external_effects_real"], label="external effect flag")
    _digest(payload["registry_digest"], label="registry digest")
    _digest(payload["test_manifest_digest"], label="test manifest digest")
    source = _validate_source(payload["source_identity"])
    del source
    profile = _object(payload["profile"], fields=_PROFILE_FIELDS, label="profile")
    _text(profile["profile_id"], label="profile id")
    _texts(profile["claims"], label="profile claims")
    _texts(profile["excludes"], label="profile excludes")
    selection = _object(
        payload["selection"], fields=_SELECTION_FIELDS, label="selection"
    )
    selection_id = _text(selection["selection_id"], label="selection id")
    if selection_id not in {"full", "premerge_subset"}:
        raise _error("selection id is unknown")
    _texts(selection["scenario_ids"], label="selected scenario ids")
    _validate_harness(payload["harness"])
    _validate_test_manifest(payload["test_manifest"])
    _validate_implementation(payload["implementation"])
    scenario_results = [
        _validate_scenario_result(item, index=index)
        for index, item in enumerate(
            _list(payload["scenario_results"], label="scenario_results")
        )
    ]
    _validate_sorted_records(
        scenario_results, key="scenario_id", label="scenario_results"
    )
    invariants = [
        _validate_invariant_result(item, index=index)
        for index, item in enumerate(_list(payload["invariants"], label="invariants"))
    ]
    _validate_sorted_records(invariants, key="invariant_id", label="invariants")
    gaps = [
        _validate_gap(item, index=index)
        for index, item in enumerate(_list(payload["gaps"], label="gaps"))
    ]
    _validate_sorted_records(gaps, key="gap_id", label="gaps")
    p0_records = [
        _validate_p0(item, index=index)
        for index, item in enumerate(_list(payload["p0_records"], label="p0_records"))
    ]
    _validate_sorted_records(p0_records, key="p0_id", label="p0_records")
    _texts(payload["rejection_reasons"], label="rejection reasons")
    return payload


def load_report_bytes(content: bytes) -> LoadedArchitectureQualificationReport:
    raw = _strict_json(content)
    envelope = _object(raw, fields=_REPORT_FIELDS, label="report envelope")
    if envelope["schema_id"] != QUALIFICATION_REPORT_SCHEMA_ID:
        raise _error("qualification report schema is unsupported")
    payload = _validate_payload(envelope["payload"])
    payload_digest = _digest(envelope["payload_digest"], label="payload digest")
    if payload_digest != _sha256(canonical_json_bytes(payload)):
        raise _error("qualification report payload digest drifted")
    if content != canonical_json_document_bytes(envelope):
        raise _error("qualification report bytes are not canonical JSON plus one LF")
    return LoadedArchitectureQualificationReport(
        envelope=envelope,
        payload=payload,
        payload_digest=payload_digest,
    )


def load_report(path: Path) -> LoadedArchitectureQualificationReport:
    try:
        if path.is_symlink() or not path.is_file():
            raise _error("qualification report path must be a regular file")
        content = path.read_bytes()
    except ArchitectureQualificationReportError:
        raise
    except OSError as exc:
        raise _error("qualification report cannot be read") from exc
    return load_report_bytes(content)


def _manifest_from_bound_payload(
    payload: Mapping[str, object],
    *,
    registry: ValidatedInvariantRegistry,
    repo_root: Path,
) -> ValidatedTestManifest:
    raw_scenarios = _list(payload.get("scenarios"), label="bound manifest scenarios")
    collected = tuple(
        CollectedQualificationScenario(
            scenario_id=str(item["scenario_id"]),
            family=str(item["family"]),
            node_id=str(item["collected_node_id"]),
            source_file=str(item["source_files"][0]["path"]),
            selections=tuple(str(value) for value in item["selections"]),
        )
        for item in raw_scenarios
        if isinstance(item, Mapping)
        and isinstance(item.get("source_files"), list)
        and len(item["source_files"]) == 1
        and isinstance(item["source_files"][0], Mapping)
    )
    if len(collected) != len(raw_scenarios):
        raise _error("bound test manifest scenarios are not reconstructable")
    try:
        manifest = build_test_manifest(
            registry,
            collected_scenarios=collected,
            repo_root=repo_root,
        )
    except Exception as exc:  # noqa: BLE001 - normalize all manifest drift
        raise _error("bound test manifest does not match the current checkout") from exc
    if dict(manifest.payload) != dict(payload):
        raise _error("bound test manifest payload drifted")
    return manifest


def verify_report(
    report: LoadedArchitectureQualificationReport | Path | bytes,
    *,
    repo_root: Path,
    runner_path: Path,
) -> ArchitectureQualificationVerification:
    loaded = (
        report
        if isinstance(report, LoadedArchitectureQualificationReport)
        else load_report_bytes(report)
        if isinstance(report, bytes)
        else load_report(report)
    )
    root = _canonical_repo_root(repo_root)
    payload = loaded.payload
    current_source = collect_source_identity(repo_root=root)
    if dict(payload["source_identity"]) != dict(current_source):
        raise _error("qualification report source identity differs from checkout")
    registry = load_invariant_registry(repo_root=root)
    if payload["registry_digest"] != registry.registry_digest:
        raise _error("qualification report registry digest differs from checkout")
    manifest = _manifest_from_bound_payload(
        payload["test_manifest"],
        registry=registry,
        repo_root=root,
    )
    if payload["test_manifest_digest"] != manifest.test_manifest_digest:
        raise _error("qualification report test manifest digest drifted")
    expected_implementation = _implementation_identity(
        repo_root=root,
        runner_path=runner_path,
        test_manifest=manifest.payload,
    )
    if dict(payload["implementation"]) != expected_implementation:
        raise _error("qualification implementation identity differs from checkout")
    if dict(payload["profile"]) != _profile(registry):
        raise _error("qualification report profile differs from registry")
    mode = str(payload["mode"])
    selection = _selection(mode=mode, registry=registry)
    if dict(payload["selection"]) != selection:
        raise _error("qualification report scenario selection drifted")

    raw_results = [
        _execution_facts(item)
        for item in payload["scenario_results"]
        if isinstance(item, Mapping)
    ]
    expected_scenarios = _normalize_scenario_results(
        raw_results,
        registry=registry,
        selection=selection,
    )
    if payload["scenario_results"] != expected_scenarios:
        raise _error("qualification scenario status or budget closure drifted")
    expected_invariants = _invariant_results(
        registry=registry,
        scenario_results=expected_scenarios,
    )
    if payload["invariants"] != expected_invariants:
        raise _error("qualification invariant status closure drifted")
    closed_p0_records = _load_p0_closure_records(
        repo_root=root,
        registry=registry,
    )
    expected_gaps, expected_p0 = _gap_and_p0_records(
        registry=registry,
        invariant_results=expected_invariants,
        scenario_results=expected_scenarios,
        closed_p0_records=closed_p0_records,
    )
    if payload["gaps"] != expected_gaps:
        raise _error("qualification GAP taxonomy closure drifted")
    if payload["p0_records"] != expected_p0:
        raise _error("qualification P0 closure drifted")
    external_effects_real = any(
        bool(item["external_effects_real"]) for item in expected_scenarios
    )
    if payload["external_effects_real"] is not external_effects_real:
        raise _error("qualification external-effect summary drifted")
    if payload["aox_live_started"] is not False:
        raise _error("qualification report cannot claim an AOX live start")
    expected_rejections, expected_eligible = _rejection_and_eligibility(
        mode=mode,
        source_identity=current_source,
        selection=selection,
        harness=payload["harness"],
        scenario_results=expected_scenarios,
        invariant_results=expected_invariants,
        p0_records=expected_p0,
        external_effects_real=external_effects_real,
        aox_live_started=False,
    )
    if payload["rejection_reasons"] != expected_rejections:
        raise _error("qualification rejection reasons drifted")
    if payload["admission_eligible"] is not expected_eligible:
        raise _error("qualification admission eligibility drifted")
    return ArchitectureQualificationVerification(
        admission_eligible=expected_eligible,
        payload_digest=loaded.payload_digest,
        rejection_reasons=tuple(expected_rejections),
        source_commit=str(current_source["commit"]),
    )


def publish_report(
    report: LoadedArchitectureQualificationReport,
    *,
    output_directory: Path,
    repo_root: Path,
) -> Path:
    root = _canonical_repo_root(repo_root)
    if not output_directory.is_absolute():
        raise _error("qualification output directory must be absolute")
    lexical = Path(os.path.normpath(str(output_directory)))
    if lexical != output_directory:
        raise _error("qualification output directory must be lexically canonical")
    if output_directory.exists() or output_directory.is_symlink():
        raise _error("qualification output directory already exists")
    try:
        parent = output_directory.parent.resolve(strict=True)
    except OSError as exc:
        raise _error("qualification output parent is unavailable") from exc
    if output_directory.parent.absolute() != parent:
        raise _error("qualification output parent aliases another directory")
    target_directory = parent / output_directory.name
    try:
        target_directory.relative_to(root)
    except ValueError:
        pass
    else:
        raise _error("qualification output must remain outside the checkout")
    content = canonical_json_document_bytes(report.envelope)
    os.mkdir(target_directory, mode=0o700)
    target = target_directory / "architecture-qualification-report.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(target, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    directory_fd = os.open(target_directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    parent_fd = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return target


__all__ = [
    "build_report",
    "collect_source_identity",
    "load_report",
    "load_report_bytes",
    "publish_report",
    "verify_report",
]
