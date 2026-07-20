from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from openzyme_runtime import REPO_ROOT

from .aox_browser_observation import BrowserObservationReceiptError
from .aox_browser_observation import build_browser_observation_receipt
from .aox_browser_observation import load_json_object
from .aox_browser_observation import load_screenshot_png
from .aox_browser_observation import publish_browser_observation_receipt
from .aox_cutover_evidence import AttemptRunRecord
from .aox_cutover_evidence import AoxCutoverCampaign
from .aox_cutover_evidence import create_blank_world_roots
from .aox_cutover_evidence import evaluate_campaign
from .aox_cutover_evidence import safe_micu_ledger_snapshot
from .aox_cutover_evidence import seal_campaign_decision
from .aox_cutover_evidence import verify_attempt_bundle
from .aox_cutover_launch import AoxCutoverDriverConfig
from .aox_cutover_launch import AoxCutoverLaunchError
from .aox_cutover_launch import pin_aox_cutover_launch
from .aox_cutover_launch import prepare_aox_cutover_launch
from .aox_cutover_runtime_config import AOX_CUTOVER_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
from .aox_cutover_runtime_config import AOX_CUTOVER_MAX_SIGNALS_PER_DRAIN


_PIN_COMMIT_BASENAME = ".aox-cutover-pin-commit.json"
_PIN_COMMIT_SCHEMA_ID = "aox_cutover_pin_commit@1"
_PIN_COMMIT_FIELDS = frozenset(
    {
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
        )
    )


def _driver_from_args(args: argparse.Namespace) -> AoxCutoverDriverConfig:
    return AoxCutoverDriverConfig(
        approval_mode=args.approval_mode,
        timeout_seconds=args.timeout_seconds,
        max_drains=args.max_drains,
        max_signals_per_drain=args.max_signals_per_drain,
        max_steps_per_agent=args.max_steps_per_agent,
        browser_poll_interval_seconds=args.browser_poll_interval_seconds,
        browser_approval_timeout_seconds=args.browser_approval_timeout_seconds,
        browser_completion_hold_seconds=args.browser_completion_hold_seconds,
        browser_observation_submission_timeout_seconds=(
            args.browser_observation_submission_timeout_seconds
        ),
    )


def _browser_receipt(args: argparse.Namespace) -> int:
    handoff = load_json_object(args.handoff, label="browser handoff")
    capture = load_json_object(args.capture, label="Chrome capture")
    receipt = build_browser_observation_receipt(
        handoff=handoff,
        capture=capture,
        screenshot_png=load_screenshot_png(args.screenshot),
    )
    target = publish_browser_observation_receipt(
        handoff=handoff,
        receipt=receipt,
        output=args.output,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    _print(
        {
            "schema_id": "aox_browser_observation_publish_receipt@1",
            "status": "published",
            "output_file": target.name,
            "raw_receipt_digest": _canonical_digest(receipt),
            "raw_receipt_field_count": len(receipt),
        }
    )
    return 0


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
) -> dict[str, str]:
    return {
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
) -> tuple[dict[str, object], dict[str, object]]:
    identity_target = _existing_pin_target(identity_path)
    prerequisites_target = _existing_pin_target(prerequisites_path)
    if (
        identity_target == prerequisites_target
        or identity_target.parent != prerequisites_target.parent
        or _PIN_COMMIT_BASENAME
        in {identity_target.name, prerequisites_target.name}
    ):
        raise AoxCutoverLaunchError(
            "aox_launch_pin_commit_invalid",
            "AOX pinned declarations do not form one committed transaction",
        )
    commit_target = _existing_pin_target(
        identity_target.parent / _PIN_COMMIT_BASENAME
    )
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
    )
    if set(commit) != _PIN_COMMIT_FIELDS or commit != expected_commit:
        raise AoxCutoverLaunchError(
            "aox_launch_pin_commit_invalid",
            "AOX declaration commit marker does not bind the exact pinned payloads",
        )
    return identity, prerequisites


def _pin(args: argparse.Namespace) -> int:
    from openzyme_runtime import OpenZymeSettings

    identity_target, prerequisites_target = _pin_output_targets(
        args.identity_output,
        args.allowed_prerequisites_output,
    )
    settings = OpenZymeSettings.from_env()
    ledger_path = (
        Path(settings.test.live_llm.token_ledger_path)
        if args.ledger_path is None
        else args.ledger_path
    )
    launch = pin_aox_cutover_launch(
        settings=settings,
        driver=_driver_from_args(args),
        ledger_path=ledger_path,
    )
    _write_pin_outputs_atomic_no_replace(
        identity_target=identity_target,
        prerequisites_target=prerequisites_target,
        identity=launch.identity,
        prerequisites=launch.allowed_prerequisites,
    )
    _print(
        {
            "schema_id": "aox_cutover_pin_receipt@1",
            "status": "pinned",
            "git_commit": launch.identity["git_commit"],
            "config_digest": launch.identity["config_digest"],
            "declaration_commit_digest": _canonical_digest(
                _pin_commit_payload(
                    identity_target=identity_target,
                    prerequisites_target=prerequisites_target,
                    identity=launch.identity,
                    prerequisites=launch.allowed_prerequisites,
                )
            ),
        }
    )
    return 0


def _preflight(args: argparse.Namespace) -> int:
    prerequisites = _json_object(args.allowed_prerequisites)
    roots = create_blank_world_roots(
        args.campaign_root,
        attempt_kind=args.attempt_kind,
        attempt_id=args.attempt_id,
        allowed_prerequisites=prerequisites,
    )
    _print(
        {
            "proof": roots.proof,
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


def _decide(args: argparse.Namespace) -> int:
    records: list[AttemptRunRecord] = []
    for bundle_path, artifact_root in args.attempt:
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
    _print(safe_micu_ledger_snapshot(args.path))
    return 0


def _run_live(args: argparse.Namespace) -> int:
    from openzyme_runtime import OpenZymeSettings

    from .aox_cutover_live import LiveAoxAttemptRunner

    identity, prerequisites = _load_pinned_declarations(
        args.identity,
        args.allowed_prerequisites,
    )
    settings = OpenZymeSettings.from_env()
    ledger_path = (
        Path(settings.test.live_llm.token_ledger_path)
        if args.ledger_path is None
        else args.ledger_path
    )
    driver = _driver_from_args(args)
    launch = prepare_aox_cutover_launch(
        settings=settings,
        driver=driver,
        ledger_path=ledger_path,
        declared_identity=identity,
        declared_prerequisites=prerequisites,
    )
    runner = LiveAoxAttemptRunner(
        settings=launch.effective_settings,
        ledger_path=ledger_path,
        effective_config=launch.effective_config,
        approval_mode=args.approval_mode,
        timeout_seconds=args.timeout_seconds,
        max_drains=args.max_drains,
        max_signals_per_drain=args.max_signals_per_drain,
        max_steps_per_agent=args.max_steps_per_agent,
        browser_poll_interval_seconds=args.browser_poll_interval_seconds,
        browser_approval_timeout_seconds=args.browser_approval_timeout_seconds,
        browser_completion_hold_seconds=args.browser_completion_hold_seconds,
        browser_observation_submission_timeout_seconds=(
            args.browser_observation_submission_timeout_seconds
        ),
        browser_observation_receipt_path=args.browser_observation_receipt,
    )
    campaign = AoxCutoverCampaign(
        campaign_root=args.campaign_root,
        identity=launch.identity,
        ledger_path=ledger_path,
        positive_runner=runner,
        fault_runner=runner,
        allowed_prerequisites=launch.allowed_prerequisites,
        launch_guard=launch.assert_unchanged,
    )
    records, decision = campaign.run()
    _print(
        {
            "decision": decision,
            "attempts": [
                {
                    "attempt_id": record.attempt_id,
                    "attempt_kind": record.attempt_kind,
                    "bundle_path": str(record.bundle_path),
                    "artifact_root": str(record.artifact_root),
                    "bundle_digest": record.bundle_digest,
                    "verification": record.verification.to_dict(),
                }
                for record in records
            ],
            "micu_ledger": safe_micu_ledger_snapshot(ledger_path),
        }
    )
    return 0 if decision["decision"] == "GO" else 2


def _add_driver_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--approval-mode",
        choices=("auto", "chrome-once"),
        default="auto",
        help=(
            "chrome-once exposes positive 1 through the same-process loopback Host "
            "and waits for the first formal approval from the Web UI"
        ),
    )
    parser.add_argument(
        "--browser-poll-interval-seconds",
        type=float,
        default=0.5,
        help="bounded Host polling interval for the Chrome approval/observation path",
    )
    parser.add_argument(
        "--browser-approval-timeout-seconds",
        type=float,
        default=300.0,
        help=(
            "independent Chrome approval deadline measured from the emitted handoff; "
            "it never extends the total attempt deadline"
        ),
    )
    parser.add_argument(
        "--browser-completion-hold-seconds",
        type=float,
        default=60.0,
        help="bounded UI observation window after the Chrome-gated positive completes",
    )
    parser.add_argument(
        "--browser-observation-submission-timeout-seconds",
        type=float,
        default=180.0,
        help=(
            "positive finite deadline for atomically submitting the challenged "
            "DevTools observation after the Host-held completion window"
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=AOX_CUTOVER_DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        help=(
            "per-session AOX deadline; the launch gate rejects values below the "
            "sealed long-operation hierarchy"
        ),
    )
    parser.add_argument("--max-drains", type=int, default=120)
    parser.add_argument(
        "--max-signals-per-drain",
        type=int,
        default=AOX_CUTOVER_MAX_SIGNALS_PER_DRAIN,
        help=(
            "must remain 1 so cutover inspects durable terminal state between "
            "agent signals"
        ),
    )
    parser.add_argument("--max-steps-per-agent", type=int, default=16)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and offline-verify the AOX/HMM blank-world cutover campaign."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    _add_driver_arguments(pin)
    pin.set_defaults(handler=_pin)

    preflight = subparsers.add_parser(
        "preflight",
        help="create one unique empty attempt root and emit its local launch paths",
    )
    preflight.add_argument("--campaign-root", required=True, type=Path)
    preflight.add_argument(
        "--attempt-kind",
        required=True,
        choices=("positive", "fault"),
    )
    preflight.add_argument("--attempt-id")
    preflight.add_argument("--allowed-prerequisites", required=True, type=Path)
    preflight.set_defaults(handler=_preflight)

    verify = subparsers.add_parser(
        "verify",
        help="verify one sealed attempt without network access",
    )
    verify.add_argument("--bundle", required=True, type=Path)
    verify.add_argument("--artifact-root", required=True, type=Path)
    verify.set_defaults(handler=_verify)

    decide = subparsers.add_parser(
        "decide",
        help="derive GO/NO-GO from two positive bundles followed by one fault bundle",
    )
    decide.add_argument(
        "--attempt",
        required=True,
        action="append",
        nargs=2,
        metavar=("BUNDLE", "ARTIFACT_ROOT"),
        type=Path,
    )
    decide.add_argument("--output", type=Path)
    decide.set_defaults(handler=_decide)

    ledger = subparsers.add_parser(
        "ledger",
        help="read a safe cumulative MICU ledger snapshot without resetting it",
    )
    ledger.add_argument("--path", required=True, type=Path)
    ledger.set_defaults(handler=_ledger)

    browser_receipt = subparsers.add_parser(
        "browser-receipt",
        help=(
            "build and durably publish the exact challenged Chrome observation "
            "receipt after its Host-held not-before time"
        ),
    )
    browser_receipt.add_argument(
        "--handoff",
        required=True,
        type=Path,
        help="ready_for_completion_observation operator-record JSON",
    )
    browser_receipt.add_argument(
        "--capture",
        required=True,
        type=Path,
        help="trusted Chrome MCP capture JSON",
    )
    browser_receipt.add_argument(
        "--screenshot",
        required=True,
        type=Path,
        help="PNG written by the challenged Chrome page target",
    )
    browser_receipt.add_argument(
        "--output",
        type=Path,
        help="must equal the exact receipt target carried by the handoff",
    )
    browser_receipt.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=0.05,
        help="bounded target-absence poll interval while waiting for not-before",
    )
    browser_receipt.set_defaults(handler=_browser_receipt)

    run_live = subparsers.add_parser(
        "run-live",
        help=(
            "run the real same-process public Host campaign; any missing product "
            "receipt is sealed as NO-GO"
        ),
    )
    run_live.add_argument("--campaign-root", required=True, type=Path)
    run_live.add_argument(
        "--identity",
        required=True,
        type=Path,
        help="digest-pinned campaign identity JSON",
    )
    run_live.add_argument(
        "--allowed-prerequisites",
        required=True,
        type=Path,
        help="closed blank-world prerequisite JSON",
    )
    run_live.add_argument(
        "--ledger-path",
        type=Path,
        help=(
            "persistent MICU ledger; defaults to the exact configured live-LLM ledger"
        ),
    )
    run_live.add_argument(
        "--browser-observation-receipt",
        type=Path,
        help=(
            "append-only Chrome DevTools MCP observation JSON written in response "
            "to the live handoff challenge; required by chrome-once positive 1"
        ),
    )
    _add_driver_arguments(run_live)
    run_live.set_defaults(handler=_run_live)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = args.handler
    try:
        return int(handler(args))
    except BrowserObservationReceiptError as exc:
        print(
            json.dumps(
                {
                    "schema_id": "aox_browser_observation_builder_failure@1",
                    "status": "failed",
                    "failure_code": exc.code,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except AoxCutoverLaunchError as exc:
        # Launch failures can wrap SSH/provider/config exceptions whose repr may
        # contain private locators or credentials.  The operator boundary gets
        # only the stable public code; Python's chained traceback stays closed.
        print(
            json.dumps(
                {
                    "schema_id": "aox_cutover_launch_failure@1",
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


__all__ = ["build_parser", "main"]
