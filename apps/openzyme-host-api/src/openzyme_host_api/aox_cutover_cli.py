from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import REPO_ROOT

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
from .aox_attempt_authority import claim_aox_attempt_authority_slot
from .aox_attempt_authority import consume_aox_attempt_authority_plan
from .aox_attempt_authority import attempt_authority_consumption_path
from .aox_attempt_authority import load_aox_attempt_authority_plan
from .aox_attempt_authority import load_aox_attempt_authority_consumption
from .aox_attempt_authority import publish_aox_attempt_authority_plan
from .aox_attempt_preflight import build_attempt_preflight_receipt
from .aox_attempt_preflight import publish_attempt_preflight_receipt
from .aox_attempt_preflight import publish_attempt_slot_claim_evidence
from .aox_cutover_evidence import AttemptRunRecord
from .aox_cutover_evidence import create_blank_world_roots
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_cutover_evidence import evaluate_campaign
from .aox_cutover_evidence import safe_micu_ledger_snapshot
from .aox_cutover_evidence import seal_campaign_decision
from .aox_cutover_evidence import verify_attempt_bundle
from .aox_cutover_launch import AoxCutoverLaunchError
from .aox_cutover_launch import build_aox_cutover_effective_config
from .aox_cutover_launch import pin_aox_cutover_launch
from .aox_cutover_launch import validate_aox_authority_wall_time
from .aox_host_supervision import DEFAULT_KILL_GRACE_SECONDS
from .aox_host_supervision import DEFAULT_STARTUP_TIMEOUT_SECONDS
from .aox_host_supervision import DEFAULT_TERM_GRACE_SECONDS
from .aox_host_supervision import HostSupervisionError
from .aox_host_supervision import supervised_attempt_host
from .aox_formal_slot_failure import evaluate_formal_slot_failure
from .aox_formal_slot_failure import finalize_and_seal_formal_slot_failure
from .aox_formal_slot_failure import seal_formal_slot_failure_decision
from .aox_formal_slot_failure import verify_formal_slot_failure
from .aox_public_conductor_bundle import (
    finalize_and_seal_public_conductor_bundle,
)


_PIN_COMMIT_BASENAME = ".aox-cutover-pin-commit.json"
_PIN_COMMIT_SCHEMA_ID = "aox_cutover_pin_commit@2"
_PIN_COMMIT_FIELDS = frozenset(
    {
        "architecture_qualification",
        "schema_id",
        "identity_file",
        "allowed_prerequisites_file",
        "identity_digest",
        "allowed_prerequisites_digest",
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


_PUBLIC_SCHEMA_PATH_PATTERN = re.compile(
    r"^effective_config(?:\.[A-Za-z0-9_-]+|\[[0-9]+\])*$"
)
_PUBLIC_SCHEMA_FIELD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,255}$")
_PUBLIC_RUNNER_TOOL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
_PUBLIC_RUNNER_ERROR_CODE_PATTERN = re.compile(
    r"(?:[A-Z][A-Z0-9_]{0,63}|[a-z][a-z0-9_]{0,95})"
)
_PUBLIC_RUNNER_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_PUBLIC_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_PUBLIC_RUNNER_STAGES = frozenset({"runner_call", "runner_result"})
_PUBLIC_RUNNER_EFFECT_CERTAINTIES = frozenset(
    {
        "no_effect",
        "dispatch_in_doubt",
        "effect_known",
        "terminal_known",
        "unproven",
    }
)


def _public_launch_failure_details(
    exc: AoxCutoverLaunchError,
) -> dict[str, object] | None:
    raw = exc.public_details
    kind = raw.get("kind") if raw else None
    if kind == "runner_attestation":
        if not set(raw).issubset(
            {
                "kind",
                "tool_id",
                "stage",
                "effect_certainty",
                "runner_error_code",
                "runner_run_id",
                "runner_attempt_receipt_digest",
            }
        ):
            return None
        tool_id = raw.get("tool_id")
        stage = raw.get("stage")
        effect_certainty = raw.get("effect_certainty")
        if (
            not isinstance(tool_id, str)
            or _PUBLIC_RUNNER_TOOL_ID_PATTERN.fullmatch(tool_id) is None
            or stage not in _PUBLIC_RUNNER_STAGES
            or effect_certainty not in _PUBLIC_RUNNER_EFFECT_CERTAINTIES
        ):
            return None
        normalized_runner: dict[str, object] = {
            "kind": kind,
            "tool_id": tool_id,
            "stage": stage,
            "effect_certainty": effect_certainty,
        }
        if "runner_run_id" in raw:
            runner_run_id = raw["runner_run_id"]
            if (
                not isinstance(runner_run_id, str)
                or _PUBLIC_RUNNER_ID_PATTERN.fullmatch(runner_run_id) is None
            ):
                return None
            normalized_runner["runner_run_id"] = runner_run_id
        if "runner_attempt_receipt_digest" in raw:
            runner_attempt_receipt_digest = raw[
                "runner_attempt_receipt_digest"
            ]
            if (
                not isinstance(runner_attempt_receipt_digest, str)
                or _PUBLIC_DIGEST_PATTERN.fullmatch(
                    runner_attempt_receipt_digest
                )
                is None
            ):
                return None
            normalized_runner["runner_attempt_receipt_digest"] = (
                runner_attempt_receipt_digest
            )
        if "runner_error_code" in raw:
            runner_error_code = raw["runner_error_code"]
            if (
                not isinstance(runner_error_code, str)
                or _PUBLIC_RUNNER_ERROR_CODE_PATTERN.fullmatch(runner_error_code)
                is None
            ):
                return None
            normalized_runner["runner_error_code"] = runner_error_code
        return normalized_runner
    if kind != "schema_field" or not set(raw).issubset(
        {"kind", "identity", "missing", "unexpected"}
    ):
        return None
    identity = raw.get("identity")
    if (
        not isinstance(identity, str)
        or _PUBLIC_SCHEMA_PATH_PATTERN.fullmatch(identity) is None
    ):
        return None
    normalized: dict[str, object] = {"kind": kind, "identity": identity}
    for key in ("missing", "unexpected"):
        if key not in raw:
            continue
        values = raw[key]
        if (
            not isinstance(values, (list, tuple))
            or any(
                not isinstance(value, str)
                or _PUBLIC_SCHEMA_FIELD_PATTERN.fullmatch(value) is None
                for value in values
            )
            or list(values) != sorted(set(values))
        ):
            return None
        normalized[key] = list(values)
    return normalized


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
) -> tuple[Path, Path]:
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
    _pin_output_target(identity_target.parent / _PIN_COMMIT_BASENAME)
    return identity_target, prerequisites_target


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
    identity: object,
    prerequisites: object,
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
        "identity_digest": _canonical_digest(identity),
        "allowed_prerequisites_digest": _canonical_digest(prerequisites),
    }


def _write_pin_outputs_atomic_no_replace(
    *,
    identity_target: Path,
    prerequisites_target: Path,
    identity: object,
    prerequisites: object,
    architecture_qualification: object,
) -> None:
    staged: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    if identity_target.parent != prerequisites_target.parent:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_parent_mismatch",
            "AOX pin declarations must share one transaction directory",
        )
    parent = identity_target.parent
    commit_target = parent / _PIN_COMMIT_BASENAME
    if commit_target in {identity_target, prerequisites_target}:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_output_collision",
            "AOX declaration output collides with its transaction commit marker",
        )
    commit_payload = _pin_commit_payload(
        identity_target=identity_target,
        prerequisites_target=prerequisites_target,
        identity=identity,
        prerequisites=prerequisites,
        architecture_qualification=architecture_qualification,
    )
    try:
        for target, payload in (
            (identity_target, identity),
            (prerequisites_target, prerequisites),
            (commit_target, commit_payload),
        ):
            temporary_path = _stage_pin_json(target, payload)
            staged.append((temporary_path, target))
        for temporary_path, target in staged[:2]:
            os.link(temporary_path, target, follow_symlinks=False)
            installed.append(target)
        # Payloads must be durable before the one-link commit point can appear.
        _fsync_directory(parent)
        commit_temporary, commit_target = staged[2]
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
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
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
    try:
        identity = _json_object(identity_target)
        prerequisites = _json_object(prerequisites_target)
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
        identity=identity,
        prerequisites=prerequisites,
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
    return identity, prerequisites, dict(architecture_qualification)


def _check_config(args: argparse.Namespace) -> int:
    settings, ledger_path = _configured_settings_and_ledger(args.ledger_path)
    effective_config = build_aox_cutover_effective_config(
        settings,
        ledger_path=ledger_path,
    )
    _print(
        {
            "schema_id": "aox_cutover_config_check@1",
            "status": "valid",
            "effective_config_schema_id": effective_config.payload["schema_id"],
            "config_digest": effective_config.digest,
        }
    )
    return 0


def _pin(args: argparse.Namespace) -> int:

    earliest_architecture_qualification = verify_aox_architecture_qualification_report(
        args.architecture_qualification_report,
    )
    identity_target, prerequisites_target = _pin_output_targets(
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
    _write_pin_outputs_atomic_no_replace(
        identity_target=identity_target,
        prerequisites_target=prerequisites_target,
        identity=launch.identity,
        prerequisites=launch.allowed_prerequisites,
        architecture_qualification=launch.architecture_qualification,
    )
    _print(
        {
            "schema_id": "aox_cutover_pin_receipt@2",
            "status": "pinned",
            "architecture_qualification": launch.architecture_qualification,
            "git_commit": launch.identity["git_commit"],
            "config_digest": launch.identity["config_digest"],
            "declaration_commit_digest": _canonical_digest(
                _pin_commit_payload(
                    identity_target=identity_target,
                    prerequisites_target=prerequisites_target,
                    identity=launch.identity,
                    prerequisites=launch.allowed_prerequisites,
                    architecture_qualification=launch.architecture_qualification,
                )
            ),
        }
    )
    return 0


def _preflight(args: argparse.Namespace) -> int:
    current_qualification = verify_aox_architecture_qualification_report(
        args.architecture_qualification_report,
    )
    identity, prerequisites, pinned_qualification = _load_pinned_declarations(
        args.identity,
        args.allowed_prerequisites,
    )
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
    )
    consumption_path = args.attempt_authority_consumption.expanduser().resolve(
        strict=True
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
    settings = OpenZymeSettings.from_env()
    effective_config = build_aox_cutover_effective_config(
        settings,
        ledger_path=Path(settings.test.live_llm.token_ledger_path),
    )
    if effective_config.digest != identity.get("config_digest"):
        raise AoxCutoverLaunchError(
            "aox_preflight_config_drift",
            "AOX preflight configuration differs from the pinned identity",
        )
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
    receipt = build_attempt_preflight_receipt(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=architecture_qualification,
        effective_config=effective_config.payload,
        authority_plan=plan,
        authority_consumption=consumption,
        slot=slot,
        slot_claim=slot_claim,
        roots=roots,
    )
    receipt_path = publish_attempt_preflight_receipt(receipt, roots=roots)
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
        try:
            lease.wait()
        except KeyboardInterrupt:
            lease.shutdown_reason = "operator_stop"
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


def _finalize_and_seal(args: argparse.Namespace) -> int:
    bundle_path, bundle_digest = finalize_and_seal_public_conductor_bundle(
        identity_path=args.identity,
        preflight_path=args.preflight_receipt,
        receipt_chain_path=args.receipt_chain,
        workspace_response_path=args.workspace_response,
        event_response_path=args.event_response,
        evidence_response_path=args.evidence_response,
        handoff_response_paths=args.handoff_response,
        ledger_before_path=args.ledger_before,
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
    failure_path, failure_digest = finalize_and_seal_formal_slot_failure(
        identity_path=args.identity,
        preflight_path=args.preflight_receipt,
        receipt_chain_path=args.receipt_chain,
        workspace_response_path=args.workspace_response,
        event_response_path=args.event_response,
        handoff_response_paths=args.handoff_response,
        ledger_before_path=args.ledger_before,
        ledger_after_path=args.ledger_after,
    )
    _print(
        {
            "schema_id": "aox_formal_slot_failure_seal_receipt@1",
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


def _decide(args: argparse.Namespace) -> int:
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
    identity, prerequisites, pinned_qualification = _load_pinned_declarations(
        args.identity,
        args.allowed_prerequisites,
    )
    qualification = require_matching_architecture_qualification_receipt(
        pinned_qualification,
        current_qualification,
    )
    target = _pin_output_target(args.output)
    plan = build_aox_attempt_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
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
) -> tuple[dict[str, object], dict[str, object], dict[str, str]]:
    earliest_architecture_qualification = verify_aox_architecture_qualification_report(
        args.architecture_qualification_report,
    )
    identity, prerequisites, pinned_architecture_qualification = (
        _load_pinned_declarations(
            args.identity,
            args.allowed_prerequisites,
        )
    )
    require_matching_architecture_qualification_receipt(
        pinned_architecture_qualification,
        earliest_architecture_qualification,
    )
    return identity, prerequisites, pinned_architecture_qualification


def _consume_authority(args: argparse.Namespace) -> int:
    identity, prerequisites, architecture_qualification = _load_authority_declarations(
        args
    )
    plan = load_aox_attempt_authority_plan(
        args.attempt_authority_plan,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=architecture_qualification,
    )
    plan_path = args.attempt_authority_plan.expanduser().resolve(strict=True)
    target = _pin_output_target(args.attempt_authority_consumption)
    expected_target = attempt_authority_consumption_path(plan_path)
    if target != expected_target:
        raise CutoverEvidenceError(
            "attempt_authority_consumption_target_mismatch",
            "authority consumption must use the deterministic sibling target",
            details={"expected_file": expected_target.name},
        )
    receipt = consume_aox_attempt_authority_plan(
        plan,
        plan_path=plan_path,
        path=target,
    )
    _print(
        {
            "schema_id": "aox_attempt_authority_consume_receipt@1",
            "status": "consumed_without_execution",
            "campaign_id": plan["campaign_id"],
            "plan_digest": plan["plan_digest"],
            "consumption_digest": _canonical_digest(receipt),
            "output_file": target.name,
        }
    )
    return 0


def _required_path_arguments(
    parser: argparse.ArgumentParser, *names: str
) -> None:
    for name in names:
        parser.add_argument(f"--{name.replace('_', '-')}", required=True, type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and offline-verify the AOX/HMM blank-world cutover campaign."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_config = subparsers.add_parser(
        "check-config",
        help=(
            "validate the current AOX effective configuration locally without "
            "runner attestation or persistent state"
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
        "attempt_authority_consumption",
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
        "receipt_chain",
        "workspace_response",
        "event_response",
        "evidence_response",
        "ledger_before",
        "ledger_after",
    )
    finalize_and_seal.add_argument(
        "--handoff-response",
        action="append",
        required=True,
        type=Path,
        help=(
            "sealed drain, terminal command-status, or pre-grant workspace "
            "response; repeat for every bounded handoff"
        ),
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
        "receipt_chain",
        "workspace_response",
        "event_response",
        "ledger_before",
        "ledger_after",
    )
    seal_slot_failure.add_argument(
        "--handoff-response",
        action="append",
        default=[],
        type=Path,
        help=(
            "sealed drain admission or terminal command-status response; "
            "repeat for every bounded handoff"
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
        "--attempt-authority-consumption", required=True, type=Path
    )
    consume_authority.set_defaults(handler=_consume_authority)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = args.handler
    try:
        return int(handler(args))
    except (AoxArchitectureQualificationError, AoxCutoverLaunchError) as exc:
        # 启动失败可能包裹含私有定位信息或凭据的异常。只有错误源明确标记为
        # 可公开的字段级详情才能越过操作员边界；异常链本身始终保持封闭。
        payload: dict[str, object] = {
            "schema_id": "aox_cutover_launch_failure@3",
            "status": "failed",
            "failure_code": exc.code,
        }
        if isinstance(exc, AoxCutoverLaunchError):
            public_details = _public_launch_failure_details(exc)
            if public_details is not None:
                payload["failure_details"] = public_details
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
