from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .aox_cutover_evidence import AttemptRunRecord
from .aox_cutover_evidence import AoxCutoverCampaign
from .aox_cutover_evidence import create_blank_world_roots
from .aox_cutover_evidence import evaluate_campaign
from .aox_cutover_evidence import safe_micu_ledger_snapshot
from .aox_cutover_evidence import seal_campaign_decision
from .aox_cutover_evidence import verify_attempt_bundle
from .aox_cutover_launch import AoxCutoverDriverConfig
from .aox_cutover_launch import prepare_aox_cutover_launch


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

    identity = _json_object(args.identity)
    prerequisites = _json_object(args.allowed_prerequisites)
    settings = OpenZymeSettings.from_env()
    ledger_path = (
        Path(settings.test.live_llm.token_ledger_path)
        if args.ledger_path is None
        else args.ledger_path
    )
    driver = AoxCutoverDriverConfig(
        approval_mode=args.approval_mode,
        timeout_seconds=args.timeout_seconds,
        max_drains=args.max_drains,
        max_signals_per_drain=args.max_signals_per_drain,
        max_steps_per_agent=args.max_steps_per_agent,
        browser_approval_timeout_seconds=args.browser_approval_timeout_seconds,
        browser_completion_hold_seconds=args.browser_completion_hold_seconds,
    )
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
        browser_approval_timeout_seconds=args.browser_approval_timeout_seconds,
        browser_completion_hold_seconds=args.browser_completion_hold_seconds,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and offline-verify the AOX/HMM blank-world cutover campaign."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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
        "--approval-mode",
        choices=("auto", "chrome-once"),
        default="auto",
        help=(
            "chrome-once exposes positive 1 through the same-process loopback Host "
            "and waits for the first formal approval from the Web UI"
        ),
    )
    run_live.add_argument(
        "--browser-approval-timeout-seconds",
        type=float,
        default=300.0,
        help=(
            "independent Chrome approval deadline measured from the emitted handoff; "
            "it never extends the total attempt deadline"
        ),
    )
    run_live.add_argument(
        "--browser-completion-hold-seconds",
        type=float,
        default=60.0,
        help="bounded UI observation window after the Chrome-gated positive completes",
    )
    run_live.add_argument(
        "--browser-observation-receipt",
        type=Path,
        help=(
            "append-only Chrome DevTools MCP observation JSON written in response "
            "to the live handoff challenge; required by chrome-once positive 1"
        ),
    )
    run_live.add_argument("--timeout-seconds", type=float, default=1_800.0)
    run_live.add_argument("--max-drains", type=int, default=120)
    run_live.add_argument("--max-signals-per-drain", type=int, default=10)
    run_live.add_argument("--max-steps-per-agent", type=int, default=16)
    run_live.set_defaults(handler=_run_live)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = args.handler
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
