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
from .architecture_qualification import ArchitectureQualificationOutputError
from .architecture_qualification import ArchitectureQualificationVerification
from .architecture_qualification import CollectedQualificationScenario
from .architecture_qualification import LoadedArchitectureQualificationReport
from .architecture_qualification import QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID
from .architecture_qualification import QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID_V1
from .architecture_qualification import QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID_V2
from .architecture_qualification import QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID_V3
from .architecture_qualification import QUALIFICATION_REPORT_SCHEMA_ID
from .architecture_qualification import QUALIFICATION_REPORT_SCHEMA_ID_V1
from .architecture_qualification import QUALIFICATION_REPORT_SCHEMA_ID_V2
from .architecture_qualification import QUALIFICATION_REPORT_SCHEMA_ID_V3
from .architecture_qualification import ValidatedInvariantRegistry
from .architecture_qualification import ValidatedTestManifest
from .architecture_qualification import ValidatedQualificationOutputTarget
from .architecture_qualification import build_test_manifest
from .architecture_qualification import canonical_json_bytes
from .architecture_qualification import canonical_json_document_bytes
from .architecture_qualification import load_invariant_registry


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_CHANGE_REF = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_MODES = frozenset({"admission", "diagnostic", "premerge_subset"})
P0_CLOSURE_SCHEMA_ID = "openzyme_v3_architecture_p0_closures@1"
P0_CLOSURE_RELATIVE_PATH = Path("docs/v3/architecture-qualification/p0-closures.json")
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
_PAYLOAD_FIELDS_V1 = frozenset(
    {
        "admission_eligible",
        "live_campaign_started",
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
_PAYLOAD_FIELDS_V2 = frozenset(
    set(_PAYLOAD_FIELDS_V1)
    | {
        "not_run_scenario_ids",
        "process_receipts",
        "run_evidence_digest",
        "run_failure",
        "source_revalidations",
        "terminal_source_identity",
    }
)
_PAYLOAD_FIELDS_V3 = frozenset(
    set(_PAYLOAD_FIELDS_V2)
    | {
        "owner_constraint_registry_digest",
        "transformation_results_digest",
    }
)
_PAYLOAD_FIELDS = frozenset(
    (
        set(_PAYLOAD_FIELDS_V2)
        | {
            "qualification_bindings",
            "profiles",
            "owner_constraint_registry_digest",
            "transformation_results_digest",
        }
    )
    - {"profile"}
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
_PROFILE_FIELDS = frozenset(
    {
        "allowed_external_port_ids",
        "claims",
        "component_manifest_refs",
        "database_mode",
        "distribution_id",
        "document_refs",
        "excludes",
        "import_root_refs",
        "layered_composition_digests",
        "process_model",
        "profile_id",
        "semantic_owner_ids",
        "trust_boundary",
        "wheel_distribution_names",
    }
)
_PROFILE_FIELDS_V3 = frozenset({"claims", "excludes", "profile_id"})
_QUALIFICATION_BINDING_FIELDS = frozenset(
    {
        "catalog_bundle_digest",
        "distribution_bundle_digest",
        "documentation_bundle_digest",
        "inventory_bundle_digest",
        "openspec_change_digest",
        "profile_bundle_digest",
        "schema_bundle_digest",
        "test_selection_digest",
        "wheel_set_digest",
    }
)
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
_IDENTITY_FIELDS = frozenset({"files", "implementation_digest", "runner", "verifier"})
_VERIFIER_FIELDS = frozenset({"content_digest", "files"})
_SCENARIO_RESULT_FIELDS_V3 = frozenset(
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
_SCENARIO_RESULT_FIELDS = frozenset(set(_SCENARIO_RESULT_FIELDS_V3) | {"profile_ids"})
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
_INVARIANT_RESULT_FIELDS_V3 = frozenset(
    {
        "evidence_digest",
        "family",
        "invariant_id",
        "scenario_ids",
        "status",
    }
)
_INVARIANT_RESULT_FIELDS = frozenset(set(_INVARIANT_RESULT_FIELDS_V3) | {"profile_ids"})
_GAP_FIELDS_V3 = frozenset(
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
_GAP_FIELDS = frozenset((set(_GAP_FIELDS_V3) - {"profile_id"}) | {"profile_ids"})
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
_SOURCE_REVALIDATION_FIELDS = frozenset(
    {"matched_admission", "phase_id", "source_identity_digest"}
)
_PROCESS_RECEIPT_SCHEMA_ID = "openzyme_v3_qualification_process_receipt@1"
_PROCESS_RECEIPT_FIELDS = frozenset(
    {
        "command",
        "duration_milliseconds",
        "error_code",
        "exit_code",
        "kill_sent",
        "outcome",
        "phase_id",
        "receipt_digest",
        "scenario_id",
        "schema_id",
        "source_identity_digest",
        "stderr",
        "stdout",
        "term_sent",
        "timed_out",
    }
)
_PROCESS_STREAM_FIELDS = frozenset({"digest", "tail", "total_bytes"})
_RUN_FAILURE_FIELDS = frozenset(
    {
        "cause_id",
        "phase_id",
        "process_receipt_digest",
        "scenario_id",
        "source_identity_digest",
    }
)
_RUN_FAILURE_CAUSES = frozenset(
    {
        "architecture_qualification_collection_failed",
        "architecture_qualification_harness_failed",
        "architecture_qualification_scenario_execution_failed",
        "architecture_qualification_source_drift",
    }
)


def _error(message: str) -> ArchitectureQualificationReportError:
    return ArchitectureQualificationReportError(message)


def _output_error(message: str) -> ArchitectureQualificationOutputError:
    return ArchitectureQualificationOutputError(message)


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
    if (
        path.is_absolute()
        or text != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
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
        if (
            candidate.is_symlink()
            or not resolved.is_file()
            or relative.as_posix() != normalized
        ):
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
        raise _error(
            "qualification implementation file is outside the repository"
        ) from exc
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
    files = _list(
        test_manifest.get("implementation_files"), label="implementation files"
    )
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


def collect_implementation_identity(
    *,
    repo_root: Path,
    runner_path: Path,
    test_manifest: Mapping[str, object],
) -> dict[str, object]:
    """Capture the qualification implementation at lock admission."""

    return _implementation_identity(
        repo_root=repo_root,
        runner_path=runner_path,
        test_manifest=test_manifest,
    )


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
        report_record = {key: record[key] for key in sorted(_P0_FIELDS)}
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
            raise _error(
                "P0 closure registry red scenario is not owned by its invariant"
            )
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
    not_run_scenario_ids: Sequence[str] = (),
) -> list[dict[str, object]]:
    scenarios, _ = _registry_records(registry)
    selected_ids = list(selection["scenario_ids"])
    by_id: dict[str, Mapping[str, object]] = {}
    for raw in raw_results:
        scenario_id = str(raw.get("scenario_id") or "")
        if scenario_id in by_id:
            raise _error(f"scenario result {scenario_id!r} is duplicated")
        by_id[scenario_id] = raw
    not_run = [str(item) for item in not_run_scenario_ids]
    if not_run != sorted(set(not_run)):
        raise _error("not-run scenario ids must be sorted and unique")
    if sorted([*by_id, *not_run]) != selected_ids or set(by_id) & set(not_run):
        raise _error(
            "scenario results and not-run ids do not close the selected scenario set"
        )

    normalized: list[dict[str, object]] = []
    for scenario_id in sorted(by_id):
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
            raise _error(f"scenario {scenario_id!r} recorded an undeclared P0 trigger")
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
            "profile_ids": list(expected["profile_ids"]),
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
                "profile_ids": list(invariant["profile_ids"]),
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
    scenario_evidence = {str(item["scenario_id"]): item for item in scenario_results}
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
            "profile_ids": list(invariant["profile_ids"]),
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
        str(item["invariant_id"]): str(item["status"]) for item in invariant_results
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
    live_campaign_started: bool,
    not_run_scenario_ids: Sequence[str] = (),
    run_failure: Mapping[str, object] | None = None,
    source_stable: bool = True,
    process_chain_complete: bool = True,
    source_revalidation_complete: bool = True,
) -> tuple[list[str], bool]:
    reasons: list[str] = []
    if mode != "admission":
        reasons.append("mode_not_admission")
    if selection["selection_id"] != "full":
        reasons.append("selection_not_full")
    if source_identity["worktree_clean"] is not True:
        reasons.append("source_not_clean")
    if not source_stable:
        reasons.append("source_identity_not_stable")
    if not process_chain_complete:
        reasons.append("process_receipt_chain_not_complete")
    if not source_revalidation_complete:
        reasons.append("source_revalidation_chain_not_complete")
    if run_failure is not None:
        reasons.append(str(run_failure["cause_id"]))
    if not_run_scenario_ids:
        reasons.append("scenarios_not_run")
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
    if live_campaign_started:
        reasons.append("live_campaign_started")
    normalized = sorted(set(reasons))
    return normalized, not normalized


def _profiles(registry: ValidatedInvariantRegistry) -> list[dict[str, object]]:
    raw_profiles = _list(registry.payload["profiles"], label="registry profiles")
    profiles = [dict(raw) for raw in raw_profiles if isinstance(raw, Mapping)]
    if len(profiles) != len(raw_profiles):
        raise _error("validated registry profiles lost object identity")
    return profiles


def _source_file_digest(
    relative_paths: Sequence[str],
    *,
    repo_root: Path,
    label: str,
) -> str:
    entries: list[dict[str, str]] = []
    for index, raw_path in enumerate(sorted(set(relative_paths))):
        normalized = _relative_source_path(raw_path, label=f"{label}[{index}]")
        path = repo_root / normalized
        try:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(repo_root)
        except (OSError, ValueError) as exc:
            raise _error(f"{label} contains an unavailable source file") from exc
        if (
            path.is_symlink()
            or not resolved.is_file()
            or relative.as_posix() != normalized
        ):
            raise _error(f"{label} must contain regular non-alias source files")
        entries.append(
            {"content_digest": _sha256(resolved.read_bytes()), "path": normalized}
        )
    return _value_digest(entries)


def _openspec_change_digest(*, repo_root: Path) -> str:
    change_root = (
        repo_root
        / "openspec/changes/separate-openzyme-kernel-from-capability-extensions"
    )
    if change_root.is_symlink() or not change_root.is_dir():
        raise _error("qualification OpenSpec change root is unavailable")
    relative_paths = sorted(
        path.relative_to(repo_root).as_posix()
        for path in change_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    if not relative_paths:
        raise _error("qualification OpenSpec change has no source files")
    return _source_file_digest(
        relative_paths,
        repo_root=repo_root,
        label="OpenSpec change files",
    )


def _qualification_bindings(
    *,
    repo_root: Path,
    registry: ValidatedInvariantRegistry,
    test_manifest: Mapping[str, object],
    selection: Mapping[str, object],
) -> dict[str, str]:
    profiles = _profiles(registry)
    documents = sorted(
        {str(path) for profile in profiles for path in profile["document_refs"]}
    )
    component_manifests = sorted(
        {
            str(path)
            for profile in profiles
            for path in profile["component_manifest_refs"]
        }
    )
    packaging_sources = sorted(
        {
            "pyproject.toml",
            "uv.lock",
            *(
                path.relative_to(repo_root).as_posix()
                for root_name in ("apps", "packages")
                for path in (repo_root / root_name).glob("*/pyproject.toml")
            ),
        }
    )
    return {
        "catalog_bundle_digest": _value_digest(
            [
                {
                    "declared_tool_catalog_digest": profile[
                        "layered_composition_digests"
                    ]["declared_tool_catalog_digest"],
                    "profile_id": profile["profile_id"],
                    "projection_catalog_digest": profile["layered_composition_digests"][
                        "projection_catalog_digest"
                    ],
                    "route_catalog_digest": profile["layered_composition_digests"][
                        "route_catalog_digest"
                    ],
                }
                for profile in profiles
            ]
        ),
        "distribution_bundle_digest": _value_digest(
            [
                {
                    "component_manifest_refs": profile["component_manifest_refs"],
                    "distribution_id": profile["distribution_id"],
                    "profile_id": profile["profile_id"],
                }
                for profile in profiles
            ]
        ),
        "documentation_bundle_digest": _source_file_digest(
            documents,
            repo_root=repo_root,
            label="qualification documents",
        ),
        "inventory_bundle_digest": _source_file_digest(
            component_manifests,
            repo_root=repo_root,
            label="qualification component manifests",
        ),
        "openspec_change_digest": _openspec_change_digest(repo_root=repo_root),
        "profile_bundle_digest": _value_digest(profiles),
        "schema_bundle_digest": _value_digest(
            {
                "owner_constraint_registry_digest": (
                    registry.owner_constraint_registry_digest
                ),
                "registry_digest": registry.registry_digest,
                "registry_schema_id": registry.payload["schema_id"],
            }
        ),
        "test_selection_digest": _value_digest(
            {
                "selection": dict(selection),
                "test_manifest": dict(test_manifest),
            }
        ),
        "wheel_set_digest": _value_digest(
            {
                "packaging_source_digest": _source_file_digest(
                    packaging_sources,
                    repo_root=repo_root,
                    label="qualification packaging sources",
                ),
                "profiles": [
                    {
                        "profile_id": profile["profile_id"],
                        "wheel_distribution_names": profile["wheel_distribution_names"],
                    }
                    for profile in profiles
                ],
            }
        ),
    }


def _run_evidence_preimage(
    *,
    terminal_source_identity: Mapping[str, object],
    source_revalidations: Sequence[Mapping[str, object]],
    process_receipts: Sequence[Mapping[str, object]],
    run_failure: Mapping[str, object] | None,
    not_run_scenario_ids: Sequence[str],
) -> dict[str, object]:
    return {
        "not_run_scenario_ids": [str(item) for item in not_run_scenario_ids],
        "process_receipts": [dict(item) for item in process_receipts],
        "run_failure": None if run_failure is None else dict(run_failure),
        "source_revalidations": [dict(item) for item in source_revalidations],
        "terminal_source_identity": dict(terminal_source_identity),
    }


def _expected_process_phases(selection: Mapping[str, object]) -> list[str]:
    return [
        "collection",
        "harness",
        *[f"scenario:{scenario_id}" for scenario_id in selection["scenario_ids"]],
    ]


def _process_chain_is_complete(
    *,
    selection: Mapping[str, object],
    process_receipts: Sequence[Mapping[str, object]],
    scenario_results: Sequence[Mapping[str, object]],
) -> bool:
    phases = [str(item["phase_id"]) for item in process_receipts]
    if phases != _expected_process_phases(selection):
        return False
    if any(item["outcome"] != "pass" for item in process_receipts[:2]):
        return False
    results = {str(item["scenario_id"]): item for item in scenario_results}
    expected_outcomes = {
        "error": "error",
        "fail": "fail",
        "pass": "pass",
        "skip": "pass",
        "xfail": "pass",
        "xpass": "fail",
    }
    return all(
        receipt["scenario_id"] in results
        and receipt["outcome"]
        == expected_outcomes.get(
            str(results[str(receipt["scenario_id"])]["pytest_outcome"]),
            "error",
        )
        for receipt in process_receipts[2:]
    )


def _source_revalidation_chain_is_complete(
    *,
    selection: Mapping[str, object],
    source_revalidations: Sequence[Mapping[str, object]],
) -> bool:
    phases = [str(item["phase_id"]) for item in source_revalidations]
    expected = [
        "lock_admission",
        "before_collection",
        "after_collection",
        "after_harness",
    ]
    for scenario_id in selection["scenario_ids"]:
        expected.extend(
            [
                f"before_scenario:{scenario_id}",
                f"after_scenario:{scenario_id}",
            ]
        )
    expected.append("pre_publication")
    return phases == expected


_TRANSFORMATION_SCENARIO_IDS = frozenset(
    {
        "strategy-neutrality.public-action-permutations",
        "world-fidelity.earliest-cause-visible",
    }
)


def _transformation_results_digest(
    scenario_results: Sequence[Mapping[str, object]],
    *,
    not_run_scenario_ids: Sequence[str],
) -> str:
    selected_results = [
        dict(item)
        for item in scenario_results
        if str(item.get("scenario_id") or "") in _TRANSFORMATION_SCENARIO_IDS
    ]
    selected_not_run = sorted(
        scenario_id
        for scenario_id in not_run_scenario_ids
        if scenario_id in _TRANSFORMATION_SCENARIO_IDS
    )
    return _value_digest(
        {
            "not_run_scenario_ids": selected_not_run,
            "scenario_results": selected_results,
            "scenario_set": sorted(_TRANSFORMATION_SCENARIO_IDS),
        }
    )


def build_report(
    *,
    repo_root: Path,
    runner_path: Path,
    mode: str,
    command: Sequence[str],
    registry: ValidatedInvariantRegistry,
    test_manifest: ValidatedTestManifest,
    source_identity: Mapping[str, object],
    terminal_source_identity: Mapping[str, object],
    source_revalidations: Sequence[Mapping[str, object]],
    process_receipts: Sequence[Mapping[str, object]],
    run_failure: Mapping[str, object] | None,
    not_run_scenario_ids: Sequence[str],
    harness_result: Mapping[str, object],
    scenario_results: Sequence[Mapping[str, object]],
    implementation_identity: Mapping[str, object] | None = None,
) -> LoadedArchitectureQualificationReport:
    if mode not in _MODES:
        raise _error("qualification report mode is unknown")
    root = _canonical_repo_root(repo_root)
    admission_source = _validate_source(dict(source_identity))
    terminal_source = _validate_source(dict(terminal_source_identity))
    normalized_revalidations = _validate_source_revalidations(source_revalidations)
    normalized_receipts = _validate_process_receipts(process_receipts)
    normalized_failure = _validate_run_failure(run_failure)
    normalized_not_run = _texts(
        list(not_run_scenario_ids),
        label="not-run scenario ids",
    )
    run_evidence_preimage = _run_evidence_preimage(
        terminal_source_identity=terminal_source,
        source_revalidations=normalized_revalidations,
        process_receipts=normalized_receipts,
        run_failure=normalized_failure,
        not_run_scenario_ids=normalized_not_run,
    )
    admission_source_digest = _value_digest(admission_source)
    source_stable = (
        admission_source == terminal_source
        and bool(normalized_revalidations)
        and all(
            item["matched_admission"] is True
            and item["source_identity_digest"] == admission_source_digest
            for item in normalized_revalidations
        )
    )
    harness = _validate_harness(dict(harness_result))
    selection = _selection(mode=mode, registry=registry)
    normalized_scenarios = _normalize_scenario_results(
        scenario_results,
        registry=registry,
        selection=selection,
        not_run_scenario_ids=normalized_not_run,
    )
    process_chain_complete = _process_chain_is_complete(
        selection=selection,
        process_receipts=normalized_receipts,
        scenario_results=normalized_scenarios,
    )
    source_revalidation_complete = _source_revalidation_chain_is_complete(
        selection=selection,
        source_revalidations=normalized_revalidations,
    )
    invariant_results = _invariant_results(
        registry=registry,
        scenario_results=normalized_scenarios,
    )
    if normalized_failure is None:
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
    else:
        gaps, p0_records = [], []
    external_effects_real = any(
        bool(item["external_effects_real"]) for item in normalized_scenarios
    )
    live_campaign_started = False
    rejection_reasons, admission_eligible = _rejection_and_eligibility(
        mode=mode,
        source_identity=admission_source,
        selection=selection,
        harness=harness,
        scenario_results=normalized_scenarios,
        invariant_results=invariant_results,
        p0_records=p0_records,
        external_effects_real=external_effects_real,
        live_campaign_started=live_campaign_started,
        not_run_scenario_ids=normalized_not_run,
        run_failure=normalized_failure,
        source_stable=source_stable,
        process_chain_complete=process_chain_complete,
        source_revalidation_complete=source_revalidation_complete,
    )
    qualification_bindings = _qualification_bindings(
        repo_root=root,
        registry=registry,
        test_manifest=test_manifest.payload,
        selection=selection,
    )
    payload: dict[str, object] = {
        "admission_eligible": admission_eligible,
        "live_campaign_started": live_campaign_started,
        "command": [str(item) for item in command],
        "external_effects_real": external_effects_real,
        "gaps": gaps,
        "harness": harness,
        "implementation": (
            _implementation_identity(
                repo_root=root,
                runner_path=runner_path,
                test_manifest=test_manifest.payload,
            )
            if implementation_identity is None
            else _validate_implementation(dict(implementation_identity))
        ),
        "invariants": invariant_results,
        "mode": mode,
        "not_run_scenario_ids": normalized_not_run,
        "owner_constraint_registry_digest": (registry.owner_constraint_registry_digest),
        "p0_records": p0_records,
        "payload_schema_id": QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID,
        "profiles": _profiles(registry),
        "process_receipts": normalized_receipts,
        "qualification_bindings": qualification_bindings,
        "registry_digest": registry.registry_digest,
        "rejection_reasons": rejection_reasons,
        "run_evidence_digest": _value_digest(run_evidence_preimage),
        "run_failure": normalized_failure,
        "scenario_results": normalized_scenarios,
        "selection": selection,
        "source_identity": dict(admission_source),
        "source_revalidations": normalized_revalidations,
        "terminal_source_identity": dict(terminal_source),
        "test_manifest": dict(test_manifest.payload),
        "test_manifest_digest": test_manifest.test_manifest_digest,
        "transformation_results_digest": _transformation_results_digest(
            normalized_scenarios,
            not_run_scenario_ids=normalized_not_run,
        ),
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
    if clean != (source["tracked_diff_digest"] == _sha256(b"") and not untracked):
        raise _error("worktree_clean contradicts the bound source identity")
    return source


def _validate_source_revalidations(
    values: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise _error(f"source_revalidations[{index}] must be an object")
        record = _object(
            dict(value),
            fields=_SOURCE_REVALIDATION_FIELDS,
            label=f"source_revalidations[{index}]",
        )
        _text(record["phase_id"], label=f"source_revalidations[{index}].phase_id")
        _digest(
            record["source_identity_digest"],
            label=f"source_revalidations[{index}].source_identity_digest",
        )
        _boolean(
            record["matched_admission"],
            label=f"source_revalidations[{index}].matched_admission",
        )
        normalized.append(dict(record))
    phase_ids = [str(item["phase_id"]) for item in normalized]
    if phase_ids != list(dict.fromkeys(phase_ids)):
        raise _error("source revalidation phases must be unique and ordered")
    return normalized


def _validate_process_stream(value: object, *, label: str) -> dict[str, object]:
    stream = _object(value, fields=_PROCESS_STREAM_FIELDS, label=label)
    _digest(stream["digest"], label=f"{label}.digest")
    _nonnegative_int(stream["total_bytes"], label=f"{label}.total_bytes")
    _text(stream["tail"], label=f"{label}.tail", allow_empty=True)
    return dict(stream)


def _validate_process_receipts(
    values: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise _error(f"process_receipts[{index}] must be an object")
        receipt = _object(
            dict(value),
            fields=_PROCESS_RECEIPT_FIELDS,
            label=f"process_receipts[{index}]",
        )
        if receipt["schema_id"] != _PROCESS_RECEIPT_SCHEMA_ID:
            raise _error("qualification process receipt schema is unsupported")
        _text(receipt["phase_id"], label=f"process_receipts[{index}].phase_id")
        _optional_text(
            receipt["scenario_id"],
            label=f"process_receipts[{index}].scenario_id",
        )
        command = _texts(
            receipt["command"],
            label=f"process_receipts[{index}].command",
            sorted_unique=False,
        )
        if not command:
            raise _error("qualification process receipt command must not be empty")
        outcome = _text(
            receipt["outcome"],
            label=f"process_receipts[{index}].outcome",
        )
        if outcome not in {"error", "fail", "pass", "timeout"}:
            raise _error("qualification process receipt outcome is unknown")
        _optional_int(
            receipt["exit_code"],
            label=f"process_receipts[{index}].exit_code",
        )
        _nonnegative_int(
            receipt["duration_milliseconds"],
            label=f"process_receipts[{index}].duration_milliseconds",
        )
        for key in ("timed_out", "term_sent", "kill_sent"):
            _boolean(receipt[key], label=f"process_receipts[{index}].{key}")
        _optional_text(
            receipt["error_code"],
            label=f"process_receipts[{index}].error_code",
        )
        _digest(
            receipt["source_identity_digest"],
            label=f"process_receipts[{index}].source_identity_digest",
        )
        _validate_process_stream(
            receipt["stdout"],
            label=f"process_receipts[{index}].stdout",
        )
        _validate_process_stream(
            receipt["stderr"],
            label=f"process_receipts[{index}].stderr",
        )
        receipt_digest = _digest(
            receipt["receipt_digest"],
            label=f"process_receipts[{index}].receipt_digest",
        )
        preimage = {key: receipt[key] for key in receipt if key != "receipt_digest"}
        if receipt_digest != _value_digest(preimage):
            raise _error("qualification process receipt digest drifted")
        normalized.append(dict(receipt))
    phase_ids = [str(item["phase_id"]) for item in normalized]
    if phase_ids != list(dict.fromkeys(phase_ids)):
        raise _error("qualification process receipt phases must be unique and ordered")
    return normalized


def _validate_run_failure(
    value: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _error("run_failure must be an object or null")
    failure = _object(dict(value), fields=_RUN_FAILURE_FIELDS, label="run_failure")
    cause_id = _text(failure["cause_id"], label="run_failure.cause_id")
    if cause_id not in _RUN_FAILURE_CAUSES:
        raise _error("qualification run failure cause is unsupported")
    _text(failure["phase_id"], label="run_failure.phase_id")
    _optional_text(
        failure["process_receipt_digest"],
        label="run_failure.process_receipt_digest",
    )
    if failure["process_receipt_digest"] is not None:
        _digest(
            failure["process_receipt_digest"],
            label="run_failure.process_receipt_digest",
        )
    _optional_text(failure["scenario_id"], label="run_failure.scenario_id")
    _digest(
        failure["source_identity_digest"],
        label="run_failure.source_identity_digest",
    )
    return dict(failure)


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
        for index, item in enumerate(
            _list(identity["files"], label="implementation.files")
        )
    ]
    _validate_sorted_records(files, key="path", label="implementation.files")
    if _digest(
        identity["implementation_digest"], label="implementation digest"
    ) != _value_digest(files):
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
    if _digest(
        verifier["content_digest"], label="verifier content digest"
    ) != _value_digest(verifier_files):
        raise _error("verifier content digest drifted")
    return identity


def _validate_scenario_result(
    value: object,
    *,
    index: int,
    schema_version: int,
) -> dict[str, Any]:
    result = _object(
        value,
        fields=(
            _SCENARIO_RESULT_FIELDS
            if schema_version >= 4
            else _SCENARIO_RESULT_FIELDS_V3
        ),
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
    if schema_version >= 4:
        _texts(result["profile_ids"], label="scenario profile ids")
    _digest(result["execution_ledger_digest"], label="execution ledger digest")
    budgets = _object(
        result["budgets"], fields=_BUDGET_FIELDS, label="scenario budgets"
    )
    for key in sorted(_BUDGET_FIELDS):
        _nonnegative_int(budgets[key], label=f"scenario budgets.{key}")
    return result


def _validate_invariant_result(
    value: object,
    *,
    index: int,
    schema_version: int,
) -> dict[str, Any]:
    result = _object(
        value,
        fields=(
            _INVARIANT_RESULT_FIELDS
            if schema_version >= 4
            else _INVARIANT_RESULT_FIELDS_V3
        ),
        label=f"invariants[{index}]",
    )
    _text(result["invariant_id"], label="invariant id")
    _text(result["family"], label="invariant family")
    status = _text(result["status"], label="invariant status")
    if status not in _QUALIFICATION_STATUSES:
        raise _error("invariant status is unknown")
    _texts(result["scenario_ids"], label="invariant scenario ids")
    if schema_version >= 4:
        _texts(result["profile_ids"], label="invariant profile ids")
    _digest(result["evidence_digest"], label="invariant evidence digest")
    return result


def _validate_gap(
    value: object,
    *,
    index: int,
    schema_version: int,
) -> dict[str, Any]:
    gap = _object(
        value,
        fields=_GAP_FIELDS if schema_version >= 4 else _GAP_FIELDS_V3,
        label=f"gaps[{index}]",
    )
    _text(gap["gap_id"], label="gap id")
    _text(gap["invariant_id"], label="gap invariant id")
    classification = _text(gap["classification"], label="gap classification")
    if classification not in _GAP_CLASSIFICATIONS:
        raise _error("gap classification is unknown")
    _text(gap["owner"], label="gap owner")
    _text(gap["reproducer"], label="gap reproducer")
    _digest(gap["evidence_digest"], label="gap evidence digest")
    if schema_version >= 4:
        _texts(gap["profile_ids"], label="gap profile ids")
    else:
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


def _validate_payload(
    value: object,
    *,
    schema_version: int = 4,
) -> dict[str, Any]:
    payload_fields = (
        _PAYLOAD_FIELDS_V1
        if schema_version == 1
        else _PAYLOAD_FIELDS_V2
        if schema_version == 2
        else _PAYLOAD_FIELDS_V3
        if schema_version == 3
        else _PAYLOAD_FIELDS
    )
    payload = _object(
        value,
        fields=payload_fields,
        label="report payload",
    )
    expected_payload_schema = (
        QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID_V1
        if schema_version == 1
        else QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID_V2
        if schema_version == 2
        else QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID_V3
        if schema_version == 3
        else QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID
    )
    if payload["payload_schema_id"] != expected_payload_schema:
        raise _error("qualification payload schema is unsupported")
    mode = _text(payload["mode"], label="report mode")
    if mode not in _MODES:
        raise _error("qualification report mode is unknown")
    command = _texts(payload["command"], label="report command", sorted_unique=False)
    if not command:
        raise _error("report command must not be empty")
    _boolean(payload["admission_eligible"], label="admission eligibility")
    _boolean(payload["live_campaign_started"], label="live campaign flag")
    _boolean(payload["external_effects_real"], label="external effect flag")
    _digest(payload["registry_digest"], label="registry digest")
    _digest(payload["test_manifest_digest"], label="test manifest digest")
    source = _validate_source(payload["source_identity"])
    del source
    if schema_version >= 4:
        profiles = [
            _object(item, fields=_PROFILE_FIELDS, label=f"profiles[{index}]")
            for index, item in enumerate(_list(payload["profiles"], label="profiles"))
        ]
        for index, profile in enumerate(profiles):
            _text(profile["profile_id"], label=f"profiles[{index}].profile_id")
            for field in (
                "allowed_external_port_ids",
                "claims",
                "component_manifest_refs",
                "document_refs",
                "excludes",
                "import_root_refs",
                "semantic_owner_ids",
                "wheel_distribution_names",
            ):
                _texts(profile[field], label=f"profiles[{index}].{field}")
            for field in (
                "database_mode",
                "distribution_id",
                "process_model",
                "trust_boundary",
            ):
                _text(profile[field], label=f"profiles[{index}].{field}")
            layered = profile["layered_composition_digests"]
            if not isinstance(layered, Mapping) or not layered:
                raise _error("profile layered composition digests must be an object")
            for key, digest in layered.items():
                _text(key, label="profile layered digest field")
                _digest(digest, label=f"profiles[{index}].{key}")
        _validate_sorted_records(profiles, key="profile_id", label="profiles")
        bindings = _object(
            payload["qualification_bindings"],
            fields=_QUALIFICATION_BINDING_FIELDS,
            label="qualification_bindings",
        )
        for field in sorted(_QUALIFICATION_BINDING_FIELDS):
            _digest(bindings[field], label=f"qualification_bindings.{field}")
    else:
        profile = _object(
            payload["profile"], fields=_PROFILE_FIELDS_V3, label="profile"
        )
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
        _validate_scenario_result(item, index=index, schema_version=schema_version)
        for index, item in enumerate(
            _list(payload["scenario_results"], label="scenario_results")
        )
    ]
    _validate_sorted_records(
        scenario_results, key="scenario_id", label="scenario_results"
    )
    invariants = [
        _validate_invariant_result(item, index=index, schema_version=schema_version)
        for index, item in enumerate(_list(payload["invariants"], label="invariants"))
    ]
    _validate_sorted_records(invariants, key="invariant_id", label="invariants")
    gaps = [
        _validate_gap(item, index=index, schema_version=schema_version)
        for index, item in enumerate(_list(payload["gaps"], label="gaps"))
    ]
    _validate_sorted_records(gaps, key="gap_id", label="gaps")
    p0_records = [
        _validate_p0(item, index=index)
        for index, item in enumerate(_list(payload["p0_records"], label="p0_records"))
    ]
    _validate_sorted_records(p0_records, key="p0_id", label="p0_records")
    _texts(payload["rejection_reasons"], label="rejection reasons")
    if schema_version == 1:
        return payload

    terminal_source = _validate_source(payload["terminal_source_identity"])
    source_revalidations = _validate_source_revalidations(
        _list(payload["source_revalidations"], label="source revalidations")
    )
    process_receipts = _validate_process_receipts(
        _list(payload["process_receipts"], label="process receipts")
    )
    run_failure = _validate_run_failure(payload["run_failure"])
    not_run_scenario_ids = _texts(
        payload["not_run_scenario_ids"],
        label="not-run scenario ids",
    )
    run_evidence_digest = _digest(
        payload["run_evidence_digest"],
        label="run evidence digest",
    )
    expected_run_evidence_digest = _value_digest(
        _run_evidence_preimage(
            terminal_source_identity=terminal_source,
            source_revalidations=source_revalidations,
            process_receipts=process_receipts,
            run_failure=run_failure,
            not_run_scenario_ids=not_run_scenario_ids,
        )
    )
    if run_evidence_digest != expected_run_evidence_digest:
        raise _error("qualification run evidence digest drifted")
    if schema_version >= 3:
        _digest(
            payload["owner_constraint_registry_digest"],
            label="owner constraint registry digest",
        )
        transformation_results_digest = _digest(
            payload["transformation_results_digest"],
            label="transformation results digest",
        )
        expected_transformation_results_digest = _transformation_results_digest(
            scenario_results,
            not_run_scenario_ids=not_run_scenario_ids,
        )
        if transformation_results_digest != expected_transformation_results_digest:
            raise _error("qualification transformation results digest drifted")
    admission_source_digest = _value_digest(payload["source_identity"])
    if any(
        receipt["source_identity_digest"] != admission_source_digest
        for receipt in process_receipts
    ):
        raise _error("qualification process receipt source binding drifted")
    receipt_digests = [str(item["receipt_digest"]) for item in process_receipts]
    receipt_phases = [str(item["phase_id"]) for item in process_receipts]
    expected_process_phases = _expected_process_phases(selection)
    if receipt_phases != expected_process_phases[: len(receipt_phases)]:
        raise _error("qualification process receipts are not a selected-chain prefix")
    if run_failure is not None:
        bound_receipt = run_failure["process_receipt_digest"]
        if bound_receipt is not None and bound_receipt not in receipt_digests:
            raise _error(
                "qualification run failure receipt is not in the selected chain"
            )
        if bound_receipt is not None and receipt_digests[-1] != bound_receipt:
            raise _error("qualification selected process chain continued after failure")
    elif receipt_phases != expected_process_phases:
        raise _error("qualification process chain ended without a typed failure")
    if run_failure is None and not_run_scenario_ids:
        raise _error("qualification not-run scenarios require a typed failure")
    if run_failure is None and payload["harness"]["outcome"] != "pass":
        raise _error("qualification harness failure requires a typed cause")
    if run_failure is not None:
        cause_id = run_failure["cause_id"]
        if cause_id == "architecture_qualification_source_drift":
            if not any(
                item["matched_admission"] is False
                and item["phase_id"] == run_failure["phase_id"]
                and item["source_identity_digest"]
                == run_failure["source_identity_digest"]
                for item in source_revalidations
            ):
                raise _error("qualification source-drift cause is not phase-bound")
        elif run_failure["source_identity_digest"] != admission_source_digest:
            raise _error("qualification process failure source binding drifted")
    selected_ids = set(selection["scenario_ids"])
    observed_ids = {str(item["scenario_id"]) for item in scenario_results}
    if (
        observed_ids & set(not_run_scenario_ids)
        or (observed_ids | set(not_run_scenario_ids)) != selected_ids
    ):
        raise _error("qualification scenario and not-run closure drifted")
    return payload


def load_report_bytes(content: bytes) -> LoadedArchitectureQualificationReport:
    raw = _strict_json(content)
    envelope = _object(raw, fields=_REPORT_FIELDS, label="report envelope")
    if envelope["schema_id"] == QUALIFICATION_REPORT_SCHEMA_ID:
        schema_version = 4
    elif envelope["schema_id"] == QUALIFICATION_REPORT_SCHEMA_ID_V3:
        schema_version = 3
    elif envelope["schema_id"] == QUALIFICATION_REPORT_SCHEMA_ID_V2:
        schema_version = 2
    elif envelope["schema_id"] == QUALIFICATION_REPORT_SCHEMA_ID_V1:
        schema_version = 1
    else:
        raise _error("qualification report schema is unsupported")
    payload = _validate_payload(envelope["payload"], schema_version=schema_version)
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
    if loaded.envelope["schema_id"] != QUALIFICATION_REPORT_SCHEMA_ID:
        raise _error(
            "historical qualification reports are read-only and not current admission evidence"
        )
    root = _canonical_repo_root(repo_root)
    payload = loaded.payload
    current_source = collect_source_identity(repo_root=root)
    if dict(payload["terminal_source_identity"]) != dict(current_source):
        raise _error("qualification terminal source identity differs from checkout")
    registry = load_invariant_registry(repo_root=root)
    if payload["registry_digest"] != registry.registry_digest:
        raise _error("qualification report registry digest differs from checkout")
    if (
        payload["owner_constraint_registry_digest"]
        != registry.owner_constraint_registry_digest
    ):
        raise _error(
            "qualification owner constraint registry digest differs from checkout"
        )
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
    if list(payload["profiles"]) != _profiles(registry):
        raise _error("qualification report profiles differ from registry")
    mode = str(payload["mode"])
    selection = _selection(mode=mode, registry=registry)
    if dict(payload["selection"]) != selection:
        raise _error("qualification report scenario selection drifted")
    expected_bindings = _qualification_bindings(
        repo_root=root,
        registry=registry,
        test_manifest=manifest.payload,
        selection=selection,
    )
    if dict(payload["qualification_bindings"]) != expected_bindings:
        raise _error("qualification report source bundle bindings drifted")

    raw_results = [
        _execution_facts(item)
        for item in payload["scenario_results"]
        if isinstance(item, Mapping)
    ]
    expected_scenarios = _normalize_scenario_results(
        raw_results,
        registry=registry,
        selection=selection,
        not_run_scenario_ids=payload["not_run_scenario_ids"],
    )
    process_chain_complete = _process_chain_is_complete(
        selection=selection,
        process_receipts=payload["process_receipts"],
        scenario_results=expected_scenarios,
    )
    source_revalidation_complete = _source_revalidation_chain_is_complete(
        selection=selection,
        source_revalidations=payload["source_revalidations"],
    )
    if payload["scenario_results"] != expected_scenarios:
        raise _error("qualification scenario status or budget closure drifted")
    if payload["transformation_results_digest"] != _transformation_results_digest(
        expected_scenarios,
        not_run_scenario_ids=payload["not_run_scenario_ids"],
    ):
        raise _error("qualification transformation result identity drifted")
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
    if payload["run_failure"] is None:
        expected_gaps, expected_p0 = _gap_and_p0_records(
            registry=registry,
            invariant_results=expected_invariants,
            scenario_results=expected_scenarios,
            closed_p0_records=closed_p0_records,
        )
    else:
        expected_gaps, expected_p0 = [], []
    if payload["gaps"] != expected_gaps:
        raise _error("qualification GAP taxonomy closure drifted")
    if payload["p0_records"] != expected_p0:
        raise _error("qualification P0 closure drifted")
    external_effects_real = any(
        bool(item["external_effects_real"]) for item in expected_scenarios
    )
    if payload["external_effects_real"] is not external_effects_real:
        raise _error("qualification external-effect summary drifted")
    if payload["live_campaign_started"] is not False:
        raise _error("qualification report cannot claim a live campaign start")
    admission_source = payload["source_identity"]
    admission_source_digest = _value_digest(admission_source)
    source_stable = (
        dict(admission_source) == dict(payload["terminal_source_identity"])
        and bool(payload["source_revalidations"])
        and all(
            item["matched_admission"] is True
            and item["source_identity_digest"] == admission_source_digest
            for item in payload["source_revalidations"]
            if isinstance(item, Mapping)
        )
        and len(payload["source_revalidations"])
        == sum(isinstance(item, Mapping) for item in payload["source_revalidations"])
    )
    expected_rejections, expected_eligible = _rejection_and_eligibility(
        mode=mode,
        source_identity=admission_source,
        selection=selection,
        harness=payload["harness"],
        scenario_results=expected_scenarios,
        invariant_results=expected_invariants,
        p0_records=expected_p0,
        external_effects_real=external_effects_real,
        live_campaign_started=False,
        not_run_scenario_ids=payload["not_run_scenario_ids"],
        run_failure=payload["run_failure"],
        source_stable=source_stable,
        process_chain_complete=process_chain_complete,
        source_revalidation_complete=source_revalidation_complete,
    )
    if payload["rejection_reasons"] != expected_rejections:
        raise _error("qualification rejection reasons drifted")
    if payload["admission_eligible"] is not expected_eligible:
        raise _error("qualification admission eligibility drifted")
    return ArchitectureQualificationVerification(
        admission_eligible=expected_eligible,
        payload_digest=loaded.payload_digest,
        rejection_reasons=tuple(expected_rejections),
        source_commit=str(admission_source["commit"]),
    )


def validate_output_target(
    *,
    output_directory: Path,
    repo_root: Path,
) -> ValidatedQualificationOutputTarget:
    root = _canonical_repo_root(repo_root)
    if not output_directory.is_absolute():
        raise _output_error("qualification output directory must be absolute")
    lexical = Path(os.path.normpath(str(output_directory)))
    if lexical != output_directory:
        raise _output_error(
            "qualification output directory must be lexically canonical"
        )
    if output_directory.exists() or output_directory.is_symlink():
        raise _output_error("qualification output directory already exists")
    try:
        parent = output_directory.parent.resolve(strict=True)
    except OSError as exc:
        raise _output_error("qualification output parent is unavailable") from exc
    if output_directory.parent.absolute() != parent:
        raise _output_error("qualification output parent aliases another directory")
    if not parent.is_dir():
        raise _output_error("qualification output parent is not a directory")
    target_directory = parent / output_directory.name
    try:
        target_directory.relative_to(root)
    except ValueError:
        pass
    else:
        raise _output_error("qualification output must remain outside the checkout")
    return ValidatedQualificationOutputTarget(
        repo_root=root,
        parent=parent,
        target_directory=target_directory,
    )


def publish_report(
    report: LoadedArchitectureQualificationReport,
    *,
    output_directory: Path,
    repo_root: Path,
) -> Path:
    validated = validate_output_target(
        output_directory=output_directory,
        repo_root=repo_root,
    )
    parent = validated.parent
    target_directory = validated.target_directory
    content = canonical_json_document_bytes(report.envelope)
    try:
        os.mkdir(target_directory, mode=0o700)
    except OSError as exc:
        raise _output_error(
            "qualification output directory could not be created without replacement"
        ) from exc
    target = target_directory / "architecture-qualification-report.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
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
    except OSError as exc:
        raise _output_error(
            "qualification report publication could not be completed"
        ) from exc
    return target


__all__ = [
    "build_report",
    "collect_implementation_identity",
    "collect_source_identity",
    "load_report",
    "load_report_bytes",
    "publish_report",
    "validate_output_target",
    "verify_report",
]
