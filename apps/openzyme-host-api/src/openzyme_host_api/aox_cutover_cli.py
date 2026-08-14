from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from mcp_hpc_runner.server import MCPHpcServer
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import REPO_ROOT
from openzyme_host_cli.client import HostApiClient
from openzyme_host_cli.client import HostApiError
from openzyme_host_cli.cli import run_cli as run_host_cli
from openzyme_host_cli.receipts import converge_public_api_mutation_receipt
from openzyme_host_cli.receipts import converge_public_response

from .aox_architecture_qualification import AoxArchitectureQualificationError
from .aox_architecture_qualification import (
    normalize_architecture_qualification_receipt,
)
from .aox_architecture_qualification import (
    require_matching_architecture_qualification_receipt,
)
from .aox_architecture_qualification import (
    verify_aox_architecture_qualification_report,
)
from .aox_attempt_authority import build_aox_attempt_authority_plan
from .aox_attempt_authority import authority_grant_payload
from .aox_attempt_authority import claim_aox_attempt_authority_slot
from .aox_attempt_authority import consume_aox_attempt_authority_plan
from .aox_attempt_authority import attempt_authority_consumption_path
from .aox_attempt_authority import attempt_authority_consumption_operation_identity
from .aox_attempt_authority import load_aox_attempt_authority_plan
from .aox_attempt_authority import load_aox_attempt_authority_consumption
from .aox_attempt_authority import observe_aox_attempt_authority_consumption
from .aox_attempt_authority import publish_aox_attempt_authority_plan
from .aox_attempt_preflight import build_attempt_preflight_receipt
from .aox_attempt_preflight import publish_attempt_launch_profile
from .aox_attempt_preflight import publish_attempt_preflight_receipt
from .aox_attempt_preflight import publish_attempt_slot_claim_evidence
from .aox_conductor_execution import (
    CONDUCTOR_RETIREMENT_READINESS_FILENAME,
)
from .aox_conductor_execution import bound_public_response_path
from .aox_conductor_execution import describe_public_host_mutation
from .aox_conductor_execution import load_active_public_host_context
from .aox_conductor_execution import load_conductor_retirement_readiness
from .aox_conductor_execution import publish_conductor_execution_contract
from .aox_conductor_execution import retirement_readiness_sources
from .aox_conductor_execution import resolve_pregrant_execution_task
from .aox_conductor_execution import seal_conductor_retirement_readiness
from .aox_conductor_execution import validate_public_host_command
from .aox_conductor_execution import validate_public_host_reconciliation
from .aox_cutover_evidence import AttemptRunRecord
from .aox_cutover_evidence import create_blank_world_roots
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_cutover_evidence import evaluate_campaign
from .aox_cutover_evidence import safe_micu_ledger_snapshot
from .aox_cutover_evidence import seal_campaign_decision
from .aox_cutover_evidence import verify_attempt_bundle
from .aox_config_contract import AoxConfigContractError
from .aox_config_contract import aox_config_contract
from .aox_config_contract import build_aox_config_candidate
from .aox_config_contract import load_aox_config_candidate
from .aox_config_contract import publish_aox_config_candidate
from .aox_config_contract import require_current_aox_config_candidate
from .aox_cutover_launch import build_aox_cutover_effective_config
from .aox_cutover_launch import pin_aox_cutover_launch
from .aox_cutover_launch import prepare_aox_cutover_launch
from .aox_cutover_launch import validate_aox_authority_wall_time
from .aox_launch_failure import AoxCutoverLaunchError
from .aox_launch_failure import aox_cutover_launch_failure_payload
from .aox_launch_profile import AOX_CUTOVER_LAUNCH_PROFILE_FILENAME
from .aox_launch_profile import build_aox_cutover_launch_profile
from .aox_launch_profile import launch_profile_digest
from .aox_launch_profile import normalize_aox_cutover_launch_profile
from .aox_launch_profile import resolve_aox_cutover_launch_profile
from .aox_host_supervision import DEFAULT_KILL_GRACE_SECONDS
from .aox_host_supervision import DEFAULT_STARTUP_TIMEOUT_SECONDS
from .aox_host_supervision import DEFAULT_TERM_GRACE_SECONDS
from .aox_host_supervision import HostSupervisionError
from .aox_host_supervision import supervised_attempt_host
from .aox_formal_slot_failure import evaluate_formal_slot_failure
from .aox_formal_slot_failure import (
    finalize_and_seal_pre_ready_formal_slot_failure,
)
from .aox_formal_slot_failure import finalize_and_seal_formal_slot_failure
from .aox_formal_slot_failure import seal_formal_slot_failure_decision
from .aox_formal_slot_failure import verify_formal_slot_failure
from .aox_public_conductor_bundle import (
    finalize_and_seal_public_conductor_bundle,
)
from .aox_preflight_failure import evaluate_formal_preflight_failure
from .aox_preflight_failure import seal_formal_preflight_failure
from .aox_preflight_failure import seal_formal_preflight_failure_decision
from .aox_preflight_failure import verify_formal_preflight_failure


_PIN_COMMIT_BASENAME = ".aox-cutover-pin-commit.json"
_PIN_COMMIT_SCHEMA_ID = "aox_cutover_pin_commit@3"
_PIN_COMMIT_FIELDS = frozenset(
    {
        "architecture_qualification",
        "schema_id",
        "identity_file",
        "allowed_prerequisites_file",
        "launch_profile_file",
        "identity_digest",
        "allowed_prerequisites_digest",
        "launch_profile_digest",
    }
)


def _canonical_digest(payload: object) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return dict(payload)


def _bundle_digest(path: Path) -> str:
    try:
        content = path.read_bytes()
        envelope = json.loads(content)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        content = f"unreadable:{path.name}".encode("utf-8")
        envelope = None
    digest = envelope.get("bundle_digest") if isinstance(envelope, dict) else None
    if isinstance(digest, str) and digest.startswith("sha256:") and len(digest) == 71:
        return digest
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _print(payload: object) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )


_PUBLIC_RUNNER_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_PUBLIC_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_PUBLIC_RUNNER_STATUSES = frozenset(
    {
        "reserved",
        "submitted",
        "queued",
        "pending",
        "running",
        "in_progress",
        "completed",
        "succeeded",
        "success",
        "cancelled",
        "canceled",
        "failed",
    }
)
_PUBLIC_RUNNER_PHASES = frozenset(
    {
        "allocated",
        "transport_ready",
        "remote_layout_ready",
        "input_staging",
        "inputs_verified",
        "preflight_passed",
        "dispatch_prepared",
        "dispatching",
        "remote_pending",
        "remote_terminal",
        "outputs_fetching",
        "outputs_verified",
        "terminal",
    }
)
_PUBLIC_RUNNER_EFFECT_CERTAINTIES = frozenset(
    {
        "no_effect",
        "dispatch_in_doubt",
        "effect_known",
        "terminal_known",
        "unproven",
    }
)
_PUBLIC_RETRY_ELIGIBILITIES = frozenset(
    {"same_phase_safe", "verify_then_retry", "reconcile_required", "terminal"}
)
def _config_candidate_public_occurrence(
    candidate: Mapping[str, object],
    *,
    publication: bool = False,
    effect_certainty: str = "no_effect",
) -> dict[str, object]:
    reconciliation_required = effect_certainty == "unproven"
    return {
        "kind": "config_candidate",
        "phase": "publication" if publication else "validation",
        "effect_certainty": effect_certainty,
        "retry_eligibility": (
            "reconcile_required" if reconciliation_required else "terminal"
        ),
        "reconciliation_required": reconciliation_required,
        "terminal_scope": (
            "config_candidate_publication_occurrence"
            if publication
            else "config_candidate_occurrence"
        ),
        "request_digest": candidate["profile_source_digest"],
        "idempotency_key": candidate["candidate_id"],
        "exact_handle": candidate["candidate_id"],
        "contract_digest": candidate["contract_digest"],
        "candidate_id": candidate["candidate_id"],
    }


def _configured_settings_and_ledger(
    ledger_path: Path | None,
) -> tuple[OpenZymeSettings, Path]:
    settings = OpenZymeSettings.from_env()
    resolved_ledger = (
        Path(settings.test.live_llm.token_ledger_path)
        if ledger_path is None
        else ledger_path
    )
    return settings, resolved_ledger


def _pin_output_target(path: Path) -> Path:
    expanded = path.expanduser()
    absolute = Path(os.path.abspath(expanded))
    try:
        parent = absolute.parent.resolve(strict=True)
    except OSError as exc:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_parent_invalid",
            "AOX pin output parent must be an existing real directory",
            details={"failure_type": type(exc).__name__},
        ) from exc
    if absolute.parent != parent or not parent.is_dir() or parent.is_symlink():
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_parent_invalid",
            "AOX pin output parent must not traverse a symbolic link",
        )
    target = parent / absolute.name
    repo_root = REPO_ROOT.resolve()
    if target == repo_root or repo_root in target.parents:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_inside_checkout",
            "AOX pin declarations must be written outside the clean checkout",
        )
    if os.path.lexists(target):
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_exists",
            "AOX pin output is append-only and already exists",
        )
    return target


def _pin_output_targets(
    identity_path: Path,
    prerequisites_path: Path,
) -> tuple[Path, Path, Path]:
    identity_target = _pin_output_target(identity_path)
    prerequisites_target = _pin_output_target(prerequisites_path)
    if identity_target == prerequisites_target:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_collision",
            "AOX identity and prerequisite outputs must use distinct paths",
        )
    if identity_target.parent != prerequisites_target.parent:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_parent_mismatch",
            "AOX pin declarations must share one transaction directory",
        )
    if _PIN_COMMIT_BASENAME in {
        identity_target.name,
        prerequisites_target.name,
    }:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_collision",
            "AOX declaration output collides with its transaction commit marker",
        )
    profile_target = _pin_output_target(
        identity_target.parent / AOX_CUTOVER_LAUNCH_PROFILE_FILENAME
    )
    if profile_target in {identity_target, prerequisites_target}:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_collision",
            "AOX launch profile collides with a declaration output",
        )
    _pin_output_target(identity_target.parent / _PIN_COMMIT_BASENAME)
    return identity_target, prerequisites_target, profile_target


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stage_pin_json(target: Path, payload: object) -> Path:
    content = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".openzyme-aox-pin-",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("atomic AOX pin write made no progress")
            offset += written
        os.fsync(descriptor)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    return temporary_path


def _pin_commit_payload(
    *,
    identity_target: Path,
    prerequisites_target: Path,
    profile_target: Path,
    identity: object,
    prerequisites: object,
    launch_profile: object,
    architecture_qualification: object,
) -> dict[str, object]:
    if not isinstance(architecture_qualification, dict):
        raise AoxArchitectureQualificationError(
            "aox_architecture_qualification_receipt_invalid",
            "AOX pin marker requires an architecture qualification receipt",
        )
    normalized_qualification = normalize_architecture_qualification_receipt(
        architecture_qualification
    )
    return {
        "architecture_qualification": normalized_qualification,
        "schema_id": _PIN_COMMIT_SCHEMA_ID,
        "identity_file": identity_target.name,
        "allowed_prerequisites_file": prerequisites_target.name,
        "launch_profile_file": profile_target.name,
        "identity_digest": _canonical_digest(identity),
        "allowed_prerequisites_digest": _canonical_digest(prerequisites),
        "launch_profile_digest": launch_profile_digest(launch_profile),
    }


def _write_pin_outputs_atomic_no_replace(
    *,
    identity_target: Path,
    prerequisites_target: Path,
    profile_target: Path,
    identity: object,
    prerequisites: object,
    launch_profile: object,
    architecture_qualification: object,
) -> None:
    staged: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    if not (
        identity_target.parent == prerequisites_target.parent == profile_target.parent
    ):
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_parent_mismatch",
            "AOX pin declarations must share one transaction directory",
        )
    parent = identity_target.parent
    commit_target = parent / _PIN_COMMIT_BASENAME
    if commit_target in {identity_target, prerequisites_target, profile_target}:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_collision",
            "AOX declaration output collides with its transaction commit marker",
        )
    commit_payload = _pin_commit_payload(
        identity_target=identity_target,
        prerequisites_target=prerequisites_target,
        profile_target=profile_target,
        identity=identity,
        prerequisites=prerequisites,
        launch_profile=launch_profile,
        architecture_qualification=architecture_qualification,
    )
    try:
        for target, payload in (
            (identity_target, identity),
            (prerequisites_target, prerequisites),
            (profile_target, launch_profile),
            (commit_target, commit_payload),
        ):
            temporary_path = _stage_pin_json(target, payload)
            staged.append((temporary_path, target))
        for temporary_path, target in staged[:3]:
            os.link(temporary_path, target, follow_symlinks=False)
            installed.append(target)
        # Payloads must be durable before the one-link commit point can appear.
        _fsync_directory(parent)
        commit_temporary, commit_target = staged[3]
        os.link(commit_temporary, commit_target, follow_symlinks=False)
        installed.append(commit_target)
        _fsync_directory(parent)
    except Exception as exc:
        for target in reversed(installed):
            target.unlink(missing_ok=True)
        try:
            _fsync_directory(parent)
        except OSError:
            pass
        code = (
            "aox_launch_pin_output_exists"
            if isinstance(exc, FileExistsError)
            else "aox_launch_pin_output_write_failed"
        )
        raise AoxCutoverLaunchError(
            code,
            "AOX pin outputs could not be atomically published without replacement",
            details={"failure_type": type(exc).__name__},
        ) from exc
    finally:
        for temporary_path, _ in staged:
            temporary_path.unlink(missing_ok=True)
        try:
            _fsync_directory(parent)
        except OSError:
            pass


def _existing_pin_target(path: Path) -> Path:
    expanded = path.expanduser()
    absolute = Path(os.path.abspath(expanded))
    try:
        parent = absolute.parent.resolve(strict=True)
    except OSError as exc:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_commit_invalid",
            "AOX pinned declarations require an existing real transaction directory",
            details={"failure_type": type(exc).__name__},
        ) from exc
    target = parent / absolute.name
    repo_root = REPO_ROOT.resolve()
    if (
        absolute.parent != parent
        or parent.is_symlink()
        or not parent.is_dir()
        or target.is_symlink()
        or not target.is_file()
        or target.resolve() != target
        or target == repo_root
        or repo_root in target.parents
    ):
        raise AoxCutoverLaunchError(
            "aox_launch_pin_commit_invalid",
            "AOX pinned declaration transaction is incomplete or unsafe",
        )
    return target


def _load_pinned_declarations(
    identity_path: Path,
    prerequisites_path: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    identity_target = _existing_pin_target(identity_path)
    prerequisites_target = _existing_pin_target(prerequisites_path)
    if (
        identity_target == prerequisites_target
        or identity_target.parent != prerequisites_target.parent
        or _PIN_COMMIT_BASENAME in {identity_target.name, prerequisites_target.name}
    ):
        raise AoxCutoverLaunchError(
            "aox_launch_pin_commit_invalid",
            "AOX pinned declarations do not form one committed transaction",
        )
    commit_target = _existing_pin_target(identity_target.parent / _PIN_COMMIT_BASENAME)
    profile_target = _existing_pin_target(
        identity_target.parent / AOX_CUTOVER_LAUNCH_PROFILE_FILENAME
    )
    try:
        identity = _json_object(identity_target)
        prerequisites = _json_object(prerequisites_target)
        launch_profile = normalize_aox_cutover_launch_profile(
            _json_object(profile_target)
        )
        commit = _json_object(commit_target)
    except (OSError, UnicodeError, ValueError) as exc:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_commit_invalid",
            "AOX pinned declaration transaction contains malformed JSON",
            details={"failure_type": type(exc).__name__},
        ) from exc
    expected_commit = _pin_commit_payload(
        identity_target=identity_target,
        prerequisites_target=prerequisites_target,
        profile_target=profile_target,
        identity=identity,
        prerequisites=prerequisites,
        launch_profile=launch_profile,
        architecture_qualification=commit.get("architecture_qualification"),
    )
    if set(commit) != _PIN_COMMIT_FIELDS or commit != expected_commit:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_commit_invalid",
            "AOX declaration commit marker does not bind the exact pinned payloads",
        )
    architecture_qualification = commit.get("architecture_qualification")
    if not isinstance(architecture_qualification, dict):
        raise AoxCutoverLaunchError(
            "aox_launch_pin_commit_invalid",
            "AOX declaration commit marker lacks architecture qualification",
        )
    return (
        identity,
        prerequisites,
        dict(architecture_qualification),
        launch_profile,
    )


def _config_contract(args: argparse.Namespace) -> int:
    del args
    _print(aox_config_contract())
    return 0


def _config_candidate(args: argparse.Namespace) -> int:
    candidate = build_aox_config_candidate(ledger_path=args.ledger_path)
    try:
        publish_aox_config_candidate(args.output, candidate)
    except AoxConfigContractError as exc:
        raise AoxCutoverLaunchError(
            exc.code,
            "AOX config candidate could not be atomically published",
            public_occurrence=_config_candidate_public_occurrence(
                candidate,
                publication=True,
                effect_certainty=(
                    "unproven"
                    if exc.code == "aox_config_candidate_publication_in_doubt"
                    else "no_effect"
                ),
            ),
        ) from exc
    _print(candidate)
    return 0


def _check_config(args: argparse.Namespace) -> int:
    current_candidate = build_aox_config_candidate(ledger_path=args.ledger_path)
    candidate: dict[str, str] | None = current_candidate
    try:
        if args.candidate is not None:
            candidate = None
            candidate = load_aox_config_candidate(args.candidate)
            candidate = require_current_aox_config_candidate(
                candidate,
                ledger_path=args.ledger_path,
            )
        assert candidate is not None
        settings, ledger_path = _configured_settings_and_ledger(args.ledger_path)
        effective_config = build_aox_cutover_effective_config(
            settings,
            ledger_path=ledger_path,
        )
    except AoxConfigContractError as exc:
        raise AoxCutoverLaunchError(
            exc.code,
            "AOX config candidate failed its public lifecycle contract",
            public_occurrence=(
                None
                if candidate is None
                else _config_candidate_public_occurrence(candidate)
            ),
        ) from exc
    except AoxCutoverLaunchError as exc:
        raise AoxCutoverLaunchError(
            exc.code,
            "AOX config candidate failed semantic validation",
            details=exc.details,
            public_occurrence=_config_candidate_public_occurrence(candidate),
            public_cause=exc.public_cause,
        ) from exc
    except Exception as exc:  # noqa: BLE001 - configuration values remain private
        raise AoxCutoverLaunchError(
            "aox_config_candidate_semantic_invalid",
            "AOX config candidate could not be parsed or semantically validated",
            public_occurrence=_config_candidate_public_occurrence(current_candidate),
        ) from exc
    _print(
        {
            "schema_id": "aox_cutover_config_check@2",
            "status": "valid",
            "candidate_id": candidate["candidate_id"],
            "contract_digest": candidate["contract_digest"],
            "candidate_digest": _canonical_digest(candidate),
            "effective_config_schema_id": effective_config.payload["schema_id"],
            "config_digest": effective_config.digest,
        }
    )
    return 0


def _pin(args: argparse.Namespace) -> int:

    earliest_architecture_qualification = verify_aox_architecture_qualification_report(
        args.architecture_qualification_report,
    )
    identity_target, prerequisites_target, profile_target = _pin_output_targets(
        args.identity_output,
        args.allowed_prerequisites_output,
    )
    settings, ledger_path = _configured_settings_and_ledger(args.ledger_path)
    launch = pin_aox_cutover_launch(
        settings=settings,
        ledger_path=ledger_path,
        architecture_qualification_report=args.architecture_qualification_report,
    )
    require_matching_architecture_qualification_receipt(
        earliest_architecture_qualification,
        launch.architecture_qualification,
    )
    launch_profile = build_aox_cutover_launch_profile(
        settings=launch.effective_settings,
        ledger_path=ledger_path,
        source_commit=str(launch.identity["git_commit"]),
        config_digest=str(launch.identity["config_digest"]),
    )
    _write_pin_outputs_atomic_no_replace(
        identity_target=identity_target,
        prerequisites_target=prerequisites_target,
        profile_target=profile_target,
        identity=launch.identity,
        prerequisites=launch.allowed_prerequisites,
        launch_profile=launch_profile,
        architecture_qualification=launch.architecture_qualification,
    )
    _print(
        {
            "schema_id": "aox_cutover_pin_receipt@3",
            "status": "pinned",
            "architecture_qualification": launch.architecture_qualification,
            "git_commit": launch.identity["git_commit"],
            "config_digest": launch.identity["config_digest"],
            "declaration_commit_digest": _canonical_digest(
                _pin_commit_payload(
                    identity_target=identity_target,
                    prerequisites_target=prerequisites_target,
                    profile_target=profile_target,
                    identity=launch.identity,
                    prerequisites=launch.allowed_prerequisites,
                    launch_profile=launch_profile,
                    architecture_qualification=launch.architecture_qualification,
                )
            ),
            "launch_profile_digest": launch_profile["profile_digest"],
        }
    )
    return 0


def _pin_operation(args: argparse.Namespace) -> int:
    try:
        server = MCPHpcServer(args.runner_config)
        operation = getattr(
            server,
            {
                "query": "inspect_reserved_execution",
                "resume": "resume_reserved_execution",
                "reconcile": "recover_reserved_execution_outcome",
            }[args.action],
        )
        result = operation(args.run_id)
    except Exception as exc:  # noqa: BLE001 - runner internals remain private
        raise AoxCutoverLaunchError(
            "aox_toolchain_pin_operation_failed",
            "AOX toolchain pin operation failed inside the trusted runner boundary",
            public_occurrence={
                "kind": "runner_attestation",
                "tool_id": "aox.toolchain-pin",
                "stage": "runner_call",
                "phase": "allocated",
                "effect_certainty": "unproven",
                "retry_eligibility": "reconcile_required",
                "reconciliation_required": True,
                "terminal_scope": "runner_operation_occurrence",
                "authority_scope": "preparation_only",
                "scientific_attempt_counted": False,
                "runner_run_id": args.run_id,
            },
        ) from exc
    required_digests = (
        "reservation_identity_digest",
        "request_digest",
        "operation_digest",
        "approval_digest",
        "runner_attempt_receipt_digest",
    )
    if (
        not isinstance(result, dict)
        or result.get("run_id") != args.run_id
        or not isinstance(result.get("status"), str)
        or result["status"] not in _PUBLIC_RUNNER_STATUSES
        or not isinstance(result.get("effect_certainty"), str)
        or result["effect_certainty"] not in _PUBLIC_RUNNER_EFFECT_CERTAINTIES
        or not isinstance(result.get("retry_eligibility"), str)
        or result["retry_eligibility"] not in _PUBLIC_RETRY_ELIGIBILITIES
        or not isinstance(result.get("phase"), str)
        or result["phase"] not in _PUBLIC_RUNNER_PHASES
        or not isinstance(result.get("reconciliation_required"), bool)
        or result["reconciliation_required"]
        != (result.get("retry_eligibility") == "reconcile_required")
        or any(
            not isinstance(result.get(key), str)
            or _PUBLIC_RUNNER_ID_PATTERN.fullmatch(str(result[key])) is None
            for key in ("execution_id", "operation_id")
        )
        or any(
            not isinstance(result.get(key), str)
            or _PUBLIC_DIGEST_PATTERN.fullmatch(str(result[key])) is None
            for key in required_digests
        )
    ):
        raise AoxCutoverLaunchError(
            "aox_toolchain_pin_operation_observation_invalid",
            "AOX toolchain pin operation returned an invalid source observation",
        )
    _print(
        {
            "schema_id": "aox_toolchain_pin_public_operation@1",
            "status": result["status"],
            "action": args.action,
            "runner_run_id": args.run_id,
            "execution_id": str(result["execution_id"]),
            "operation_id": str(result["operation_id"]),
            "operation_digest": str(result["operation_digest"]),
            "request_digest": str(result["request_digest"]),
            "reservation_identity_digest": str(result["reservation_identity_digest"]),
            "idempotency_key": str(result["reservation_identity_digest"]),
            "approval_digest": str(result["approval_digest"]),
            "receipt_locator": str(result["runner_attempt_receipt_digest"]),
            "phase": str(result["phase"]),
            "effect_certainty": str(result["effect_certainty"]),
            "retry_eligibility": str(result["retry_eligibility"]),
            "reconciliation_required": result["reconciliation_required"],
            "terminal_scope": "runner_operation_occurrence",
            "authority_scope": "preparation_only",
            "scientific_attempt_counted": False,
        }
    )
    return 0


def _preflight(args: argparse.Namespace) -> int:
    current_qualification = verify_aox_architecture_qualification_report(
        args.architecture_qualification_report,
    )
    (
        identity,
        prerequisites,
        pinned_qualification,
        launch_profile,
    ) = _load_pinned_declarations(args.identity, args.allowed_prerequisites)
    architecture_qualification = require_matching_architecture_qualification_receipt(
        pinned_qualification,
        current_qualification,
    )
    plan_path = args.attempt_authority_plan.expanduser().resolve(strict=True)
    plan = load_aox_attempt_authority_plan(
        plan_path,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=architecture_qualification,
        launch_profile=launch_profile,
    )
    asserted_consumption_path = args.attempt_authority_consumption
    consumption_path = (
        attempt_authority_consumption_path(plan_path)
        if asserted_consumption_path is None
        else Path(os.path.abspath(asserted_consumption_path.expanduser()))
    )
    consumption = load_aox_attempt_authority_consumption(
        consumption_path,
        plan=plan,
        plan_path=plan_path,
    )
    slot = dict(plan["slots"][args.slot_ordinal - 1])
    validate_aox_authority_wall_time(
        dict(slot["authority_policy"])["max_wall_time_seconds"]
    )
    try:
        settings, ledger_path = resolve_aox_cutover_launch_profile(launch_profile)
        launch = prepare_aox_cutover_launch(
            settings=settings,
            ledger_path=ledger_path,
            declared_identity=identity,
            declared_prerequisites=prerequisites,
            architecture_qualification_report=args.architecture_qualification_report,
        )
        launch.assert_unchanged()
    except AoxCutoverLaunchError as exc:
        failure_path, failure_digest = seal_formal_preflight_failure(
            plan_path=plan_path,
            campaign_root=args.campaign_root,
            slot_ordinal=args.slot_ordinal,
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=architecture_qualification,
            launch_profile=launch_profile,
            authority_plan=plan,
            authority_consumption=consumption,
            failure=aox_cutover_launch_failure_payload(exc),
        )
        _print(
            {
                "schema_id": "aox_formal_preflight_failure_seal_receipt@1",
                "status": "sealed_for_offline_reduction",
                "campaign_id": plan["campaign_id"],
                "slot_ordinal": args.slot_ordinal,
                "failure_file": str(failure_path),
                "failure_digest": failure_digest,
                "slot_claim_created": False,
                "campaign_attempt_root_created": False,
                "scientific_attempt_count": 0,
            }
        )
        raise
    slot_claim = claim_aox_attempt_authority_slot(
        plan=plan,
        consumption=consumption,
        plan_path=plan_path,
        ordinal=args.slot_ordinal,
        campaign_root=args.campaign_root,
    )
    roots = create_blank_world_roots(
        args.campaign_root,
        launch_id=str(slot_claim["launch_id"]),
        attempt_kind=str(slot["attempt_kind"]),
        allowed_prerequisites=prerequisites,
        architecture_qualification=architecture_qualification,
    )
    slot_claim_path = publish_attempt_slot_claim_evidence(
        slot_claim,
        roots=roots,
    )
    launch_profile_path = publish_attempt_launch_profile(launch_profile, roots=roots)
    receipt = build_attempt_preflight_receipt(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=architecture_qualification,
        launch_profile=launch_profile,
        effective_config=launch.effective_config,
        authority_plan=plan,
        authority_consumption=consumption,
        slot=slot,
        slot_claim=slot_claim,
        roots=roots,
    )
    receipt_path = publish_attempt_preflight_receipt(receipt, roots=roots)
    contract_path, contract = publish_conductor_execution_contract(receipt_path)
    _print(
        {
            "schema_id": "aox_attempt_preflight_publish_receipt@1",
            "status": "preflight_complete_host_not_started",
            "launch_id": slot_claim["launch_id"],
            "attempt_kind": slot["attempt_kind"],
            "session_id": slot["session_id"],
            "root_ref": slot["root_ref"],
            "authority_policy_digest": slot["authority_policy_digest"],
            "proof": roots.proof,
            "preflight_receipt": str(receipt_path),
            "preflight_receipt_digest": receipt["receipt_digest"],
            "slot_claim": str(slot_claim_path),
            "slot_claim_digest": slot_claim["claim_digest"],
            "launch_profile": str(launch_profile_path),
            "launch_profile_digest": launch_profile["profile_digest"],
            "conductor_execution_contract": str(contract_path),
            "conductor_execution_contract_digest": contract["contract_digest"],
            "local_paths": {
                key: str(path) for key, path in roots.local_paths().items()
            },
        }
    )
    return 0


def _verify(args: argparse.Namespace) -> int:
    result = verify_attempt_bundle(
        args.bundle,
        artifact_root=args.artifact_root,
    )
    _print(result.to_dict())
    return 0 if result.passed else 2


def _serve_attempt(args: argparse.Namespace) -> int:
    with supervised_attempt_host(
        args.preflight_receipt,
        startup_timeout_seconds=args.startup_timeout_seconds,
        term_grace_seconds=args.term_grace_seconds,
        kill_grace_seconds=args.kill_grace_seconds,
    ) as lease:
        _print(
            {
                "schema_id": "aox_supervised_host_handoff@1",
                "status": "ready_for_public_host_cli",
                **lease.startup_receipt,
                "startup_receipt_file": str(
                    args.preflight_receipt.parent / "aox-host-startup.json"
                ),
            }
        )
        while True:
            try:
                lease.wait()
                break
            except KeyboardInterrupt:
                readiness_path = (
                    args.preflight_receipt.parent
                    / CONDUCTOR_RETIREMENT_READINESS_FILENAME
                )
                try:
                    readiness = load_conductor_retirement_readiness(
                        readiness_path,
                        preflight_path=args.preflight_receipt,
                    )
                except CutoverEvidenceError as exc:
                    _print(
                        {
                            "schema_id": "aox_supervised_host_retirement_refused@1",
                            "status": "host_remains_active",
                            "failure_code": exc.code,
                        }
                    )
                    continue
                lease.shutdown_reason = "operator_stop"
                _print(
                    {
                        "schema_id": "aox_supervised_host_retirement_admission@1",
                        "status": "retirement_admitted",
                        "readiness_receipt_digest": readiness["receipt_digest"],
                    }
                )
                break
    receipt = lease.supervision_receipt
    if receipt is None:
        raise HostSupervisionError(
            "host_supervision_receipt_missing",
            "supervised Host retired without a terminal receipt",
        )
    _print(
        {
            "schema_id": "aox_supervised_host_retirement@1",
            "status": "retired",
            "launch_id": receipt["launch_id"],
            "shutdown_reason": receipt["shutdown_reason"],
            "receipt_digest": receipt["receipt_digest"],
            "supervision_receipt_file": str(
                args.preflight_receipt.parent / "aox-host-supervision.json"
            ),
        }
    )
    return 0


def _validate_public_host_overrides(forwarded: list[str]) -> None:
    controlled = {
        "--host",
        "--project-id",
        "--session-id",
        "--format",
        "--receipt-chain",
        "--seal-response",
    }
    if any(
        token in controlled
        or any(token.startswith(f"{option}=") for option in controlled)
        for token in forwarded
    ):
        raise CutoverEvidenceError(
            "public_conductor_command_boundary_invalid",
            "public-host owns Host, identity, format, receipt, and response binding",
            details={"identity": "host_cli_args"},
        )


def _run_bound_host_cli(
    *,
    contract: dict[str, object],
    startup: dict[str, object],
    evidence_root: Path,
    response_name: str,
    forwarded: list[str],
    host_cli_runner=None,
) -> int:
    _validate_public_host_overrides(forwarded)
    response_path = bound_public_response_path(
        evidence_root=evidence_root,
        contract=contract,
        response_name=response_name,
    )
    runner = run_host_cli if host_cli_runner is None else host_cli_runner
    return int(
        runner(
            [
                "--host",
                str(startup["base_url"]),
                "--project-id",
                str(contract["project_id"]),
                "--session-id",
                str(contract["session_id"]),
                "--format",
                "json",
                "--receipt-chain",
                str(evidence_root / str(contract["receipt_chain_name"])),
                "--seal-response",
                str(response_path),
                *forwarded,
            ]
        )
    )


def run_bound_public_host_command(
    *,
    contract: dict[str, object],
    startup: dict[str, object],
    evidence_root: Path,
    response_name: str,
    forwarded: list[str],
    host_cli_runner=None,
) -> int:
    _validate_public_host_overrides(forwarded)
    validate_public_host_command(
        contract=contract,
        evidence_root=evidence_root,
        forwarded=forwarded,
    )
    return _run_bound_host_cli(
        contract=contract,
        startup=startup,
        evidence_root=evidence_root,
        response_name=response_name,
        forwarded=forwarded,
        host_cli_runner=host_cli_runner,
    )


def run_bound_task_authority_grant(
    *,
    preflight: dict[str, object],
    contract: dict[str, object],
    startup: dict[str, object],
    evidence_root: Path,
    response_name: str,
    task_id: str,
    host_cli_runner=None,
) -> int:
    resolve_pregrant_execution_task(
        preflight=preflight,
        contract=contract,
        evidence_root=evidence_root,
        task_id=task_id,
    )
    slot = dict(preflight["slot"])
    payload = authority_grant_payload(
        slot,
        campaign_id=str(preflight["campaign_id"]),
        task_id=task_id,
    )
    payload_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    idempotency_key = str(dict(slot["authority_policy"])["idempotency_key"])
    return _run_bound_host_cli(
        contract=contract,
        startup=startup,
        evidence_root=evidence_root,
        response_name=response_name,
        forwarded=[
            "scientific",
            "authorize",
            "--payload-json",
            payload_json,
            "--idempotency-key",
            idempotency_key,
        ],
        host_cli_runner=host_cli_runner,
    )


def _public_host(args: argparse.Namespace) -> int:
    forwarded = list(args.host_cli_args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    if not forwarded:
        raise CutoverEvidenceError(
            "public_conductor_command_missing",
            "public-host requires one thin Host CLI command after --",
            details={"identity": "host_cli_args"},
        )
    _validate_public_host_overrides(forwarded)
    _, contract, startup, evidence_root = load_active_public_host_context(
        args.preflight_receipt
    )
    return run_bound_public_host_command(
        contract=contract,
        startup=startup,
        evidence_root=evidence_root,
        response_name=args.response_name,
        forwarded=forwarded,
    )


def _host_operation(args: argparse.Namespace) -> int:
    forwarded = list(args.host_cli_args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    if not forwarded:
        raise CutoverEvidenceError(
            "public_conductor_command_missing",
            "host-operation requires the exact original Host mutation after --",
            details={"identity": "host_cli_args"},
        )
    _validate_public_host_overrides(forwarded)
    preflight, contract, startup, evidence_root = load_active_public_host_context(
        args.preflight_receipt
    )
    descriptor = describe_public_host_mutation(
        forwarded,
        contract=contract,
        preflight=preflight,
    )
    client = HostApiClient(str(startup["base_url"]))
    try:
        observation = client.observe_v3_mutation_operation(
            session_id=str(contract["session_id"]),
            command_type=str(descriptor["command_type"]),
            scope_ref=str(descriptor["scope_ref"]),
            idempotency_key=str(descriptor["idempotency_key"]),
            request_digest=str(descriptor["owner_request_digest"]),
            attempt_id=(
                None
                if descriptor.get("attempt_id") is None
                else str(descriptor["attempt_id"])
            ),
            artifact_id=(
                None
                if descriptor.get("artifact_id") is None
                else str(descriptor["artifact_id"])
            ),
        )
    except HostApiError as exc:
        raise CutoverEvidenceError(
            "public_conductor_mutation_observation_failed",
            "public Host mutation owner could not be observed",
            details={"status_code": exc.status_code},
        ) from exc
    finally:
        client.close()
    if not all(
        (
            observation.get("schema_id")
            == "host_mutation_operation_observation@1",
            observation.get("session_id") == contract["session_id"],
            observation.get("command_type") == descriptor["command_type"],
            observation.get("scope_ref") == descriptor["scope_ref"],
            observation.get("idempotency_key") == descriptor["idempotency_key"],
            observation.get("query_read_only") is True,
            observation.get("resume_applicable") is False,
        )
    ):
        raise CutoverEvidenceError(
            "public_conductor_mutation_observation_drift",
            "public Host mutation observation has a different identity",
            details={"identity": "host_operation"},
        )
    terminal = observation.get("status") == "terminal"
    if terminal and observation.get("request_digest") != descriptor.get(
        "owner_request_digest"
    ):
        raise CutoverEvidenceError(
            "public_conductor_mutation_observation_drift",
            "durable Host mutation owner has different request facts",
            details={"identity": "host_operation.request_digest"},
        )
    result: dict[str, object] = {
        "schema_id": "aox_host_mutation_operation@1",
        "action": args.action,
        "status": "terminal" if terminal else "reconcile_required",
        "observation": observation,
        "request_identity": {
            "method": descriptor["method"],
            "route": descriptor["route"],
            "request_digest": _canonical_digest(descriptor["request"]),
            "idempotency_key": descriptor["idempotency_key"],
        },
        "action_applicability": {
            "query": True,
            "resume": False,
            "reconcile": True,
        },
    }
    if args.action == "query" or not terminal:
        _print(result)
        return 0 if args.action == "query" else 2
    if not args.response_name:
        raise CutoverEvidenceError(
            "public_conductor_reconciliation_response_name_required",
            "terminal Host reconciliation requires one sealed response name",
            details={"identity": "response_name"},
        )
    response = observation.get("response")
    if not isinstance(response, dict):
        raise CutoverEvidenceError(
            "public_conductor_mutation_observation_unproven",
            "durable Host mutation owner lacks a terminal response",
            details={"identity": "host_operation.response"},
        )
    validate_public_host_reconciliation(
        contract=contract,
        evidence_root=evidence_root,
        descriptor=descriptor,
    )
    receipt = converge_public_api_mutation_receipt(
        evidence_root / str(contract["receipt_chain_name"]),
        method=str(descriptor["method"]),
        route=str(descriptor["route"]),
        request_body=dict(descriptor["request_body"]),
        response_payload=response,
        status_code=int(descriptor["original_status_code"]),
        idempotency_key=str(descriptor["idempotency_key"]),
    )
    try:
        response_path = bound_public_response_path(
            evidence_root=evidence_root,
            contract=contract,
            response_name=args.response_name,
        )
    except CutoverEvidenceError as exc:
        if exc.code != "public_conductor_response_target_exists":
            raise
        response_path = evidence_root / f"public-response-{args.response_name}.json"
    envelope = converge_public_response(
        response_path,
        receipt=receipt,
        response=response,
    )
    result.update(
        {
            "status": "receipt_converged",
            "receipt": receipt,
            "response_file": response_path.name,
            "response_envelope_digest": envelope["envelope_digest"],
        }
    )
    _print(result)
    return 0


def _grant_task_authority(args: argparse.Namespace) -> int:
    preflight, contract, startup, evidence_root = load_active_public_host_context(
        args.preflight_receipt
    )
    return run_bound_task_authority_grant(
        preflight=preflight,
        contract=contract,
        startup=startup,
        evidence_root=evidence_root,
        response_name=args.response_name,
        task_id=args.task_id,
    )


def _seal_conductor_state(args: argparse.Namespace) -> int:
    path, readiness = seal_conductor_retirement_readiness(args.preflight_receipt)
    _print(
        {
            "schema_id": "aox_public_conductor_retirement_ready@1",
            "status": "ready_for_supervised_host_retirement",
            "closure_mode": readiness["closure_mode"],
            "scientific_attempt_count": readiness["scientific_attempt_count"],
            "readiness_file": str(path),
            "readiness_receipt_digest": readiness["receipt_digest"],
        }
    )
    return 0


def _finalize_and_seal(args: argparse.Namespace) -> int:
    sources = retirement_readiness_sources(
        args.retirement_readiness,
        preflight_path=args.preflight_receipt,
    )
    readiness = dict(sources["readiness"])
    if readiness.get("closure_mode") != "attempt" or sources["evidence"] is None:
        raise CutoverEvidenceError(
            "public_conductor_finalize_mode_invalid",
            "attempt finalization requires attempt-mode retirement readiness",
            details={"identity": "retirement_readiness.closure_mode"},
        )
    bundle_path, bundle_digest = finalize_and_seal_public_conductor_bundle(
        identity_path=args.identity,
        preflight_path=args.preflight_receipt,
        receipt_chain_path=sources["receipt_chain"],
        workspace_response_path=sources["workspace"],
        event_response_path=sources["events"],
        evidence_response_path=sources["evidence"],
        handoff_response_paths=sources["handoffs"],
        ledger_after_path=args.ledger_after,
    )
    _print(
        {
            "schema_id": "aox_public_conductor_finalize_receipt@1",
            "status": "sealed_for_offline_verification",
            "bundle_file": str(bundle_path),
            "bundle_digest": bundle_digest,
        }
    )
    return 0


def _seal_slot_failure(args: argparse.Namespace) -> int:
    if args.pre_ready_failure is not None:
        failure_path, failure_digest = finalize_and_seal_pre_ready_formal_slot_failure(
            identity_path=args.identity,
            preflight_path=args.preflight_receipt,
            pre_ready_failure_path=args.pre_ready_failure,
            ledger_after_path=args.ledger_after,
        )
    else:
        sources = retirement_readiness_sources(
            args.retirement_readiness,
            preflight_path=args.preflight_receipt,
        )
        readiness = dict(sources["readiness"])
        if readiness.get("closure_mode") != "slot_failure":
            raise CutoverEvidenceError(
                "formal_slot_failure_mode_invalid",
                "slot failure sealing requires zero-attempt retirement readiness",
                details={"identity": "retirement_readiness.closure_mode"},
            )
        failure_path, failure_digest = finalize_and_seal_formal_slot_failure(
            identity_path=args.identity,
            preflight_path=args.preflight_receipt,
            receipt_chain_path=sources["receipt_chain"],
            workspace_response_path=sources["workspace"],
            event_response_path=sources["events"],
            handoff_response_paths=sources["handoffs"],
            ledger_after_path=args.ledger_after,
        )
    _print(
        {
            "schema_id": "aox_formal_slot_failure_seal_receipt@2",
            "status": "sealed_for_offline_reduction",
            "failure_file": str(failure_path),
            "failure_digest": failure_digest,
        }
    )
    return 0


def _verify_slot_failure(args: argparse.Namespace) -> int:
    result = verify_formal_slot_failure(args.failure)
    _print(result.to_dict())
    return 0 if result.passed else 2


def _verify_preflight_failure(args: argparse.Namespace) -> int:
    result = verify_formal_preflight_failure(args.failure)
    _print(result.to_dict())
    return 0 if result.passed else 2


def _decide(args: argparse.Namespace) -> int:
    if getattr(args, "preflight_failure", None) is not None:
        decision = evaluate_formal_preflight_failure(args.preflight_failure)
        if args.output is not None:
            seal_formal_preflight_failure_decision(decision, args.output)
        _print(decision)
        return 2
    if args.slot_failure is not None:
        decision = evaluate_formal_slot_failure(args.slot_failure)
        if args.output is not None:
            seal_formal_slot_failure_decision(decision, args.output)
        _print(decision)
        return 2

    records: list[AttemptRunRecord] = []
    for bundle_path, artifact_root in args.attempt or ():
        verification = verify_attempt_bundle(
            bundle_path,
            artifact_root=artifact_root,
        )
        records.append(
            AttemptRunRecord(
                attempt_id=verification.attempt_id or bundle_path.parent.name,
                attempt_kind=verification.attempt_kind or "unknown",
                bundle_path=bundle_path,
                artifact_root=artifact_root,
                bundle_digest=_bundle_digest(bundle_path),
                verification=verification,
            )
        )
    decision = evaluate_campaign(records)
    if args.output is not None:
        seal_campaign_decision(decision, args.output)
    _print(decision)
    return 0 if decision["decision"] == "GO" else 2


def _ledger(args: argparse.Namespace) -> int:
    snapshot = safe_micu_ledger_snapshot(args.path)
    if args.output is not None:
        target = _pin_output_target(args.output)
        from .aox_authority_storage import publish_private_canonical_authority

        publish_private_canonical_authority(
            target,
            json.dumps(
                snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            + b"\n",
        )
    _print(snapshot)
    return 0


def _authorize(args: argparse.Namespace) -> int:
    current_qualification = verify_aox_architecture_qualification_report(
        args.architecture_qualification_report,
    )
    (
        identity,
        prerequisites,
        pinned_qualification,
        launch_profile,
    ) = _load_pinned_declarations(args.identity, args.allowed_prerequisites)
    qualification = require_matching_architecture_qualification_receipt(
        pinned_qualification,
        current_qualification,
    )
    target = _pin_output_target(args.output)
    plan = build_aox_attempt_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        launch_profile=launch_profile,
        expires_at=args.expires_at,
        max_micu_per_attempt=args.max_micu_per_attempt,
        max_cost_microunits_per_attempt=(args.max_cost_microunits_per_attempt),
        max_wall_time_seconds_per_attempt=(args.max_wall_time_seconds_per_attempt),
    )
    publish_aox_attempt_authority_plan(plan, target)
    _print(
        {
            "schema_id": "aox_attempt_authority_publish_receipt@1",
            "status": "published_not_consumed",
            "output_file": target.name,
            "campaign_id": plan["campaign_id"],
            "plan_digest": plan["plan_digest"],
            "session_ids": [slot["session_id"] for slot in plan["slots"]],
            "root_refs": [slot["root_ref"] for slot in plan["slots"]],
        }
    )
    return 0


def _load_authority_declarations(
    args: argparse.Namespace,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, str],
    dict[str, object],
]:
    earliest_architecture_qualification = verify_aox_architecture_qualification_report(
        args.architecture_qualification_report,
    )
    (
        identity,
        prerequisites,
        pinned_architecture_qualification,
        launch_profile,
    ) = _load_pinned_declarations(args.identity, args.allowed_prerequisites)
    require_matching_architecture_qualification_receipt(
        pinned_architecture_qualification,
        earliest_architecture_qualification,
    )
    return (
        identity,
        prerequisites,
        pinned_architecture_qualification,
        launch_profile,
    )


def _consume_authority(args: argparse.Namespace) -> int:
    (
        identity,
        prerequisites,
        architecture_qualification,
        launch_profile,
    ) = _load_authority_declarations(args)
    plan = load_aox_attempt_authority_plan(
        args.attempt_authority_plan,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=architecture_qualification,
        launch_profile=launch_profile,
    )
    plan_path = args.attempt_authority_plan.expanduser().resolve(strict=True)
    expected_target = attempt_authority_consumption_path(plan_path)
    target = Path(
        os.path.abspath(
            (args.attempt_authority_consumption or expected_target).expanduser()
        )
    )
    receipt = consume_aox_attempt_authority_plan(
        plan,
        plan_path=plan_path,
        path=target,
    )
    slots = [dict(item) for item in plan["slots"]]
    policies = [dict(item["authority_policy"]) for item in slots]
    operation = attempt_authority_consumption_operation_identity(
        plan,
        plan_path=plan_path,
    )
    _print(
        {
            "schema_id": "aox_attempt_authority_consume_receipt@2",
            "status": "consumption_receipt_closed",
            "campaign_id": plan["campaign_id"],
            "plan_digest": plan["plan_digest"],
            **operation,
            "consumption_digest": _canonical_digest(receipt),
            "output_file": target.name,
            "effect_certainty": "terminal_known",
            "retry_eligibility": "terminal",
            "terminal_scope": "authority_consumption_occurrence",
            "authority_slot_count": len(slots),
            "max_attempts_per_slot": policies[0]["max_attempts"],
            "max_micu_per_slot": policies[0]["max_micu"],
            "max_cost_microunits_per_slot": policies[0]["max_cost_microunits"],
            "max_wall_time_seconds_per_slot": policies[0]["max_wall_time_seconds"],
            "scientific_attempt_counted": False,
        }
    )
    return 0


def _authority_operation(args: argparse.Namespace) -> int:
    (
        identity,
        prerequisites,
        architecture_qualification,
        launch_profile,
    ) = _load_authority_declarations(args)
    plan = load_aox_attempt_authority_plan(
        args.attempt_authority_plan,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=architecture_qualification,
        launch_profile=launch_profile,
    )
    plan_path = args.attempt_authority_plan.expanduser().resolve(strict=True)
    operation = attempt_authority_consumption_operation_identity(
        plan,
        plan_path=plan_path,
    )
    receipt = observe_aox_attempt_authority_consumption(
        plan,
        plan_path=plan_path,
    )
    terminal = receipt is not None
    _print(
        {
            "schema_id": "aox_attempt_authority_operation@1",
            "action": args.action,
            "status": "terminal" if terminal else "unconsumed",
            "campaign_id": plan["campaign_id"],
            "plan_digest": plan["plan_digest"],
            **operation,
            "consumption_digest": (
                _canonical_digest(receipt) if receipt is not None else None
            ),
            "effect_certainty": "terminal_known" if terminal else "no_effect",
            "retry_eligibility": "terminal" if terminal else "not_applicable",
            "reconciliation_required": False,
            "terminal_scope": "authority_consumption_occurrence",
            "query_read_only": True,
            "action_applicability": {
                "query": True,
                "resume": False,
                "reconcile": True,
            },
        }
    )
    return 0


def _required_path_arguments(parser: argparse.ArgumentParser, *names: str) -> None:
    for name in names:
        parser.add_argument(f"--{name.replace('_', '-')}", required=True, type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and offline-verify the AOX/HMM blank-world cutover campaign."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_contract_help = (
        "print the machine-readable AOX profile descriptor and candidate "
        "lifecycle contract"
    )
    config_contract = subparsers.add_parser(
        "config-contract",
        help=config_contract_help,
        description=config_contract_help,
    )
    config_contract.set_defaults(handler=_config_contract)

    config_candidate = subparsers.add_parser(
        "config-candidate",
        help=(
            "atomically publish one credential-free identity for the current "
            "AOX profile sources without semantically validating it"
        ),
    )
    config_candidate.add_argument("--output", required=True, type=Path)
    config_candidate.add_argument(
        "--ledger-path",
        type=Path,
        help="candidate-specific MICU ledger identity override",
    )
    config_candidate.set_defaults(handler=_config_candidate)

    check_config = subparsers.add_parser(
        "check-config",
        help=(
            "validate the current AOX effective configuration locally without "
            "runner attestation or persistent state"
        ),
    )
    check_config.add_argument(
        "--candidate",
        type=Path,
        help=(
            "explicit candidate published by config-candidate; when omitted, "
            "validate an ephemeral candidate with the same identity contract"
        ),
    )
    check_config.add_argument(
        "--ledger-path",
        type=Path,
        help=(
            "persistent MICU ledger identity; defaults to the configured live-LLM "
            "ledger"
        ),
    )
    check_config.set_defaults(handler=_check_config)

    pin = subparsers.add_parser(
        "pin",
        help=(
            "derive exact launch declarations from the clean checkout and real "
            "runner-attested AOX SSH toolchains"
        ),
    )
    pin.add_argument(
        "--identity-output",
        required=True,
        type=Path,
        help="new append-only path for the generated exact-seven identity JSON",
    )
    pin.add_argument(
        "--architecture-qualification-report",
        required=True,
        type=Path,
        help="current clean-commit full architecture admission report",
    )
    pin.add_argument(
        "--allowed-prerequisites-output",
        required=True,
        type=Path,
        help="new append-only path for the generated exact-nine prerequisite JSON",
    )
    pin.add_argument(
        "--ledger-path",
        type=Path,
        help=(
            "persistent MICU ledger; defaults to the exact configured live-LLM ledger"
        ),
    )
    pin.set_defaults(handler=_pin)

    pin_operation = subparsers.add_parser(
        "pin-operation",
        help=(
            "query, explicitly resume, or reconcile one exact reserved "
            "toolchain-pin operation without creating a replacement occurrence"
        ),
    )
    pin_operation.add_argument(
        "--action",
        required=True,
        choices=("query", "resume", "reconcile"),
    )
    pin_operation.add_argument("--runner-config", required=True, type=Path)
    pin_operation.add_argument("--run-id", required=True)
    pin_operation.set_defaults(handler=_pin_operation)

    authorize = subparsers.add_parser(
        "authorize",
        help=(
            "publish a reviewable one-use three-slot authority plan without "
            "creating roots or starting live work"
        ),
    )
    authorize.add_argument("--identity", required=True, type=Path)
    authorize.add_argument("--allowed-prerequisites", required=True, type=Path)
    authorize.add_argument(
        "--architecture-qualification-report",
        required=True,
        type=Path,
    )
    authorize.add_argument("--output", required=True, type=Path)
    authorize.add_argument("--expires-at", required=True)
    authorize.add_argument(
        "--max-micu-per-attempt",
        required=True,
        type=int,
    )
    authorize.add_argument(
        "--max-cost-microunits-per-attempt",
        required=True,
        type=int,
    )
    authorize.add_argument(
        "--max-wall-time-seconds-per-attempt",
        required=True,
        type=int,
    )
    authorize.set_defaults(handler=_authorize)

    preflight = subparsers.add_parser(
        "preflight",
        help=(
            "validate one consumed authority slot, create its exact fresh root, "
            "and seal a prelaunch receipt"
        ),
    )
    _required_path_arguments(
        preflight,
        "campaign_root",
        "identity",
        "allowed_prerequisites",
        "architecture_qualification_report",
        "attempt_authority_plan",
    )
    preflight.add_argument(
        "--attempt-authority-consumption",
        type=Path,
        help=(
            "optional compatibility assertion for the exact consumption receipt; "
            "the normal path derives '<plan-name>.consumed.json' from "
            "--attempt-authority-plan"
        ),
    )
    preflight.add_argument(
        "--slot-ordinal",
        required=True,
        type=int,
        choices=(1, 2, 3),
    )
    preflight.set_defaults(handler=_preflight)

    serve_attempt = subparsers.add_parser(
        "serve-attempt",
        help=(
            "start one authority-bound loopback Host without driving messages, "
            "approvals, drains, rollover, or terminal policy"
        ),
    )
    _required_path_arguments(serve_attempt, "preflight_receipt")
    for name, default in (
        ("startup_timeout_seconds", DEFAULT_STARTUP_TIMEOUT_SECONDS),
        ("term_grace_seconds", DEFAULT_TERM_GRACE_SECONDS),
        ("kill_grace_seconds", DEFAULT_KILL_GRACE_SECONDS),
    ):
        serve_attempt.add_argument(
            f"--{name.replace('_', '-')}", type=float, default=default
        )
    serve_attempt.set_defaults(handler=_serve_attempt)

    public_host = subparsers.add_parser(
        "public-host",
        help=(
            "forward one operator-selected thin Host CLI command while binding "
            "the formal receipt chain and one sealed response"
        ),
    )
    _required_path_arguments(public_host, "preflight_receipt")
    public_host.add_argument(
        "--response-name",
        required=True,
        help=(
            "opaque unique lowercase locator for this sealed response; "
            "the receipt and response payload determine its semantic role"
        ),
    )
    public_host.add_argument(
        "host_cli_args",
        nargs=argparse.REMAINDER,
        help="thin Host CLI command after --; scientific strategy remains caller-owned",
    )
    public_host.set_defaults(handler=_public_host)

    host_operation = subparsers.add_parser(
        "host-operation",
        help=(
            "query or reconcile one exact formal Host mutation through its "
            "existing durable owner without replay"
        ),
    )
    _required_path_arguments(host_operation, "preflight_receipt")
    host_operation.add_argument(
        "--action",
        required=True,
        choices=("query", "reconcile"),
    )
    host_operation.add_argument(
        "--response-name",
        help="required for reconcile; opaque locator for the converged response",
    )
    host_operation.add_argument(
        "host_cli_args",
        nargs=argparse.REMAINDER,
        help="the exact original supported thin Host mutation after --",
    )
    host_operation.set_defaults(handler=_host_operation)

    grant_task_authority = subparsers.add_parser(
        "grant-task-authority",
        help=(
            "bind the consumed formal authority to one explicitly selected "
            "canonical execution task after its sealed public read"
        ),
    )
    _required_path_arguments(grant_task_authority, "preflight_receipt")
    grant_task_authority.add_argument(
        "--response-name",
        required=True,
        help=(
            "opaque unique lowercase locator for the sealed authority response; "
            "the receipt and response payload determine its semantic role"
        ),
    )
    grant_task_authority.add_argument(
        "--task-id",
        required=True,
        help="execution task id read from the unique sealed pre-grant workspace",
    )
    grant_task_authority.set_defaults(handler=_grant_task_authority)

    seal_conductor_state = subparsers.add_parser(
        "seal-conductor-state",
        help=(
            "verify every formal public response, bounded handoff, and final read "
            "before supervised Host retirement"
        ),
    )
    _required_path_arguments(seal_conductor_state, "preflight_receipt")
    seal_conductor_state.set_defaults(handler=_seal_conductor_state)

    finalize_and_seal = subparsers.add_parser(
        "finalize-and-seal",
        help=(
            "atomically prevalidate the authority-bound public Host receipt "
            "chain and seal one source-reconstructable @3 attempt bundle"
        ),
    )
    _required_path_arguments(
        finalize_and_seal,
        "identity",
        "preflight_receipt",
        "retirement_readiness",
        "ledger_after",
    )
    finalize_and_seal.set_defaults(handler=_finalize_and_seal)

    seal_slot_failure = subparsers.add_parser(
        "seal-slot-failure",
        help=(
            "seal one consumed formal slot that retired before any scientific "
            "attempt was created"
        ),
    )
    _required_path_arguments(
        seal_slot_failure,
        "identity",
        "preflight_receipt",
        "ledger_after",
    )
    slot_failure_source = seal_slot_failure.add_mutually_exclusive_group(required=True)
    slot_failure_source.add_argument(
        "--retirement-readiness",
        type=Path,
        help="post-child-ready public retirement-readiness receipt",
    )
    slot_failure_source.add_argument(
        "--pre-ready-failure",
        type=Path,
        help=(
            "source-bound supervised failure sealed before child-ready, Host "
            "startup, session, or public receipt creation"
        ),
    )
    seal_slot_failure.set_defaults(handler=_seal_slot_failure)

    verify = subparsers.add_parser(
        "verify",
        help="verify one sealed attempt without network access",
    )
    _required_path_arguments(verify, "bundle", "artifact_root")
    verify.set_defaults(handler=_verify)

    verify_slot_failure = subparsers.add_parser(
        "verify-slot-failure",
        help="verify one formal pre-attempt slot failure without network access",
    )
    _required_path_arguments(verify_slot_failure, "failure")
    verify_slot_failure.set_defaults(handler=_verify_slot_failure)

    verify_preflight_failure = subparsers.add_parser(
        "verify-preflight-failure",
        help=(
            "verify one consumed-authority failure that occurred before slot "
            "claim or campaign attempt-root creation"
        ),
    )
    _required_path_arguments(verify_preflight_failure, "failure")
    verify_preflight_failure.set_defaults(handler=_verify_preflight_failure)

    decide = subparsers.add_parser(
        "decide",
        help=(
            "derive GO/NO-GO from the exact three-attempt bundle chain or "
            "derive NO-GO from one verified pre-attempt formal slot failure"
        ),
    )
    decision_source = decide.add_mutually_exclusive_group(required=True)
    decision_source.add_argument(
        "--attempt",
        action="append",
        nargs=2,
        metavar=("BUNDLE", "ARTIFACT_ROOT"),
        type=Path,
    )
    decision_source.add_argument(
        "--slot-failure",
        type=Path,
        help=(
            "verified consumed-slot failure; emits canonical NO-GO without "
            "fabricating an attempt bundle"
        ),
    )
    decision_source.add_argument(
        "--preflight-failure",
        type=Path,
        help=(
            "verified consumed-authority preflight failure; emits canonical "
            "NO-GO without a slot claim, launch id, or attempt bundle"
        ),
    )
    decide.add_argument("--output", type=Path)
    decide.set_defaults(handler=_decide)

    ledger = subparsers.add_parser(
        "ledger",
        help="read a safe cumulative MICU ledger snapshot without resetting it",
    )
    ledger.add_argument("--path", required=True, type=Path)
    ledger.add_argument(
        "--output",
        type=Path,
        help="publish this cumulative snapshot once as private canonical JSON",
    )
    ledger.set_defaults(handler=_ledger)

    consume_authority = subparsers.add_parser(
        "consume-authority",
        help=(
            "consume one exact formal authority plan without creating roots or "
            "starting any Host, runtime, provider, HPC, MICU, or browser action"
        ),
    )
    consume_authority.add_argument("--identity", required=True, type=Path)
    consume_authority.add_argument(
        "--architecture-qualification-report", required=True, type=Path
    )
    consume_authority.add_argument("--allowed-prerequisites", required=True, type=Path)
    consume_authority.add_argument("--attempt-authority-plan", required=True, type=Path)
    consume_authority.add_argument(
        "--attempt-authority-consumption",
        type=Path,
        help=(
            "optional compatibility assertion for the exact output target; "
            "the normal path derives '<plan-name>.consumed.json' from "
            "--attempt-authority-plan"
        ),
    )
    consume_authority.set_defaults(handler=_consume_authority)

    authority_operation = subparsers.add_parser(
        "authority-operation",
        help=(
            "query or reconcile the deterministic authority consumption receipt "
            "without consuming or resuming it"
        ),
    )
    authority_operation.add_argument(
        "--action",
        required=True,
        choices=("query", "reconcile"),
    )
    authority_operation.add_argument("--identity", required=True, type=Path)
    authority_operation.add_argument(
        "--architecture-qualification-report", required=True, type=Path
    )
    authority_operation.add_argument(
        "--allowed-prerequisites", required=True, type=Path
    )
    authority_operation.add_argument(
        "--attempt-authority-plan", required=True, type=Path
    )
    authority_operation.set_defaults(handler=_authority_operation)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = args.handler
    try:
        return int(handler(args))
    except (AoxArchitectureQualificationError, AoxCutoverLaunchError) as exc:
        # 启动失败可能包裹含私有定位信息或凭据的异常。只有错误源明确授权的
        # occurrence/cause 投影才能越过操作员边界；异常链本身始终保持封闭。
        launch_error = (
            exc
            if isinstance(exc, AoxCutoverLaunchError)
            else AoxCutoverLaunchError(exc.code, "architecture qualification failed")
        )
        payload = aox_cutover_launch_failure_payload(launch_error)
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except HostSupervisionError as exc:
        print(
            json.dumps(
                {
                    "schema_id": "aox_supervised_host_failure@1",
                    "status": "failed",
                    "failure_code": exc.code,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except CutoverEvidenceError as exc:
        print(
            json.dumps(
                {
                    "schema_id": (
                        "aox_attempt_authority_failure@1"
                        if args.command
                        in {
                            "authorize",
                            "consume-authority",
                        }
                        else "aox_cutover_evidence_failure@1"
                    ),
                    "status": "failed",
                    "failure_code": exc.code,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception:  # noqa: BLE001 - final CLI secrecy/fail-closed boundary
        # Environment parsing, filesystem decoding, or an unexpected provider
        # exception can include the offending secret/path in its message.  Do
        # not print the exception or chained traceback.  Keep the command so
        # offline verification failures are not mislabeled as launch failures.
        print(
            json.dumps(
                {
                    "schema_id": "aox_cutover_cli_failure@1",
                    "status": "failed",
                    "command": args.command,
                    "failure_code": "aox_cutover_cli_unhandled_failure",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
