#!/usr/bin/env python3
"""Repository/operator-plane entry point for staged test-gate development."""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from test_gate.affected import (
    DEFAULT_AFFECTED_SCOPE_MAP_PATH,
    AffectedScopeError,
    run_affected_scope_diagnostic,
)
from test_gate.authoritative import (
    AuthoritativePlanError,
    run_authoritative_shadow_plan,
    verify_authoritative_plan_files,
)
from test_gate.authoritative_runner import (
    AuthoritativeRunnerError,
    run_authoritative_mainline,
    run_authoritative_shadow_candidate,
    verify_authoritative_mainline_output,
    verify_authoritative_candidate_output,
)
from test_gate.benchmark import (
    BenchmarkError,
    build_legacy_baseline_summary,
    build_phase0_baseline_report,
    run_legacy_sample,
    run_legacy_stage_attribution,
)
from test_gate.config import ConfigError, TestGateConfig, load_config, validate_dispatch_profile
from test_gate.diagnostic import (
    DiagnosticError,
    run_focused_diagnostic,
    verify_diagnostic_output,
)
from test_gate.model import canonical_document_bytes, canonical_json_bytes
from test_gate.optimized_benchmark import (
    build_optimized_benchmark_summary,
    run_optimized_sample,
)
from test_gate.partition import (
    GeneralPartitionError,
    execute_general_partitions,
)
from test_gate.resource import (
    DEFAULT_RESOURCE_MANIFEST_PATH,
    ResourceManifestError,
)
from test_gate.replay import (
    DEFAULT_REPLAY_CORPUS_PATH,
    ReplayCorpusError,
    load_replay_corpus,
)
from test_gate.runner import (
    TestGateRunnerError,
    create_new_output_root,
    publish_no_replace,
    validate_new_output_root,
)
from test_gate.shadow import (
    ShadowCollectionError,
    ShadowCoverageError,
    run_shadow_collection,
)
from test_gate.source import SourceIdentityError, collect_source_identity

SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parents[1]
DEFAULT_CONFIG_PATH = SCRIPT_PATH.with_name("test-gate.toml")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "OpenZyme repository test-gate operator plane. Plans and receipts "
            "are not V3 product state, architecture admission, AOX, or live evidence."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="versioned test-gate TOML configuration",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "inspect-config",
        help="validate and print the closed configuration identity",
    )
    source_parser = subparsers.add_parser(
        "source-identity",
        help="print the exact current source/toolchain identity",
    )
    source_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )
    output_parser = subparsers.add_parser(
        "validate-output-root",
        help="validate an absolute, new, checkout-external evidence root",
    )
    output_parser.add_argument("output_root", type=Path)
    output_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )
    profile_parser = subparsers.add_parser(
        "validate-profile",
        help="validate that a profile belongs to this test-gate dispatcher",
    )
    profile_parser.add_argument("profile_id")

    focused_parser = subparsers.add_parser(
        "focused-diagnostic",
        help="run explicit focused checks with permanently non-authoritative evidence",
    )
    focused_parser.add_argument("output_root", type=Path)
    focused_parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    focused_parser.add_argument("--invocation-id")
    focused_parser.add_argument("--lint-path", action="append", default=[])
    focused_parser.add_argument("--pytest-path", action="append", default=[])
    focused_parser.add_argument("--node-id", action="append", default=[])
    focused_parser.add_argument("--contract-group", action="append", default=[])

    replay_parser = subparsers.add_parser(
        "replay-corpus",
        help=(
            "run the immutable twenty-case parity corpus as permanently "
            "non-authoritative diagnostic evidence"
        ),
    )
    replay_parser.add_argument("output_root", type=Path)
    replay_parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_REPLAY_CORPUS_PATH,
    )
    replay_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )
    replay_parser.add_argument("--invocation-id")

    affected_parser = subparsers.add_parser(
        "affected-scope-diagnostic",
        help="expand local changes through the versioned non-authoritative map",
    )
    affected_parser.add_argument("output_root", type=Path)
    affected_parser.add_argument("--base-ref", required=True)
    affected_parser.add_argument(
        "--map",
        type=Path,
        default=DEFAULT_AFFECTED_SCOPE_MAP_PATH,
    )
    affected_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )
    affected_parser.add_argument("--invocation-id")

    verify_diagnostic_parser = subparsers.add_parser(
        "verify-diagnostic",
        help="purely verify a diagnostic plan, receipt, stages, and source binding",
    )
    verify_diagnostic_parser.add_argument("plan_path", type=Path)
    verify_diagnostic_parser.add_argument("receipt_path", type=Path)
    verify_diagnostic_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )

    authoritative_plan_parser = subparsers.add_parser(
        "plan-mainline-shadow",
        help=(
            "collect and publish an exact mainline candidate plan without "
            "executing or granting authority"
        ),
    )
    authoritative_plan_parser.add_argument("output_root", type=Path)
    authoritative_plan_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )
    authoritative_plan_parser.add_argument("--invocation-id")
    authoritative_plan_parser.add_argument(
        "--resource-manifest",
        type=Path,
        default=DEFAULT_RESOURCE_MANIFEST_PATH,
    )
    authoritative_plan_parser.add_argument("--workers", type=int, default=1)

    verify_authoritative_parser = subparsers.add_parser(
        "verify-mainline-plan",
        help="purely verify a shadow mainline plan and exact residual manifest",
    )
    verify_authoritative_parser.add_argument("plan_path", type=Path)
    verify_authoritative_parser.add_argument("manifest_path", type=Path)
    verify_authoritative_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )

    verify_authoritative_receipt_parser = subparsers.add_parser(
        "verify-mainline-receipt",
        help=(
            "purely reload and verify a complete mainline candidate evidence "
            "bundle without running test stages"
        ),
    )
    verify_authoritative_receipt_parser.add_argument(
        "output_root",
        type=Path,
    )
    verify_authoritative_receipt_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )

    authoritative_mainline_parser = subparsers.add_parser(
        "mainline_authoritative",
        help=(
            "run the current complete non-live merge-authoritative mainline; "
            "this grants no admission, AOX, live, or scientific authority"
        ),
    )
    authoritative_mainline_parser.add_argument("output_root", type=Path)
    authoritative_mainline_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )
    authoritative_mainline_parser.add_argument("--invocation-id")
    authoritative_mainline_mode = (
        authoritative_mainline_parser.add_mutually_exclusive_group(
            required=True
        )
    )
    authoritative_mainline_mode.add_argument(
        "--forced-serial",
        action="store_true",
    )
    authoritative_mainline_mode.add_argument("--workers", type=int)
    authoritative_mainline_parser.add_argument(
        "--resource-manifest",
        type=Path,
        default=DEFAULT_RESOURCE_MANIFEST_PATH,
    )

    verify_mainline_parser = subparsers.add_parser(
        "verify-mainline-authoritative",
        help=(
            "purely reload and verify the current non-live "
            "merge-authoritative evidence bundle"
        ),
    )
    verify_mainline_parser.add_argument("output_root", type=Path)
    verify_mainline_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )

    authoritative_run_parser = subparsers.add_parser(
        "run-mainline-candidate",
        help=(
            "opt in to a non-authoritative full candidate comparison while "
            "scripts/check-mainline.sh remains the current authority"
        ),
    )
    authoritative_run_parser.add_argument("output_root", type=Path)
    authoritative_run_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )
    authoritative_run_parser.add_argument("--invocation-id")
    authoritative_run_mode = authoritative_run_parser.add_mutually_exclusive_group(
        required=True
    )
    authoritative_run_mode.add_argument(
        "--forced-serial",
        action="store_true",
    )
    authoritative_run_mode.add_argument("--workers", type=int)
    authoritative_run_parser.add_argument(
        "--resource-manifest",
        type=Path,
        default=DEFAULT_RESOURCE_MANIFEST_PATH,
    )

    partition_parser = subparsers.add_parser(
        "execute-general-plan",
        help=argparse.SUPPRESS,
    )
    partition_parser.add_argument("plan_path", type=Path)
    partition_parser.add_argument("manifest_path", type=Path)
    partition_parser.add_argument(
        "--resource-manifest",
        type=Path,
        required=True,
    )
    partition_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )
    partition_parser.add_argument(
        "--authoritative-mainline",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    optimized_sample_parser = subparsers.add_parser(
        "optimized-sample",
        help=(
            "run one source-bound optimized cold/warm candidate sample with "
            "CPU and I/O pressure evidence"
        ),
    )
    optimized_sample_parser.add_argument(
        "sample_kind",
        choices=("cold", "warm"),
    )
    optimized_sample_parser.add_argument("sample_index", type=int)
    optimized_sample_parser.add_argument("output_root", type=Path)
    optimized_sample_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )
    optimized_sample_parser.add_argument("--invocation-id")
    optimized_sample_mode = (
        optimized_sample_parser.add_mutually_exclusive_group(required=True)
    )
    optimized_sample_mode.add_argument(
        "--forced-serial",
        action="store_true",
    )
    optimized_sample_mode.add_argument("--workers", type=int)
    optimized_sample_parser.add_argument(
        "--resource-manifest",
        type=Path,
        default=DEFAULT_RESOURCE_MANIFEST_PATH,
    )

    optimized_summary_parser = subparsers.add_parser(
        "optimized-summary",
        help=(
            "reduce at least five optimized cold/warm pairs against a "
            "same-source legacy summary"
        ),
    )
    optimized_summary_parser.add_argument("legacy_summary", type=Path)
    optimized_summary_parser.add_argument(
        "sample_paths",
        type=Path,
        nargs="+",
    )

    shadow_parser = subparsers.add_parser(
        "shadow-collect",
        help="collect G/Qh/Qs and close legacy coverage without changing authority",
    )
    shadow_parser.add_argument("output_root", type=Path)
    shadow_parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    shadow_parser.add_argument("--invocation-id")

    sample_parser = subparsers.add_parser(
        "legacy-sample",
        help=(
            "time the frozen legacy rollback comparison; it is never the "
            "current authority"
        ),
    )
    sample_parser.add_argument("sample_kind", choices=("cold", "warm"))
    sample_parser.add_argument("sample_index", type=int)
    sample_parser.add_argument("output_root", type=Path)
    sample_parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    sample_parser.add_argument("--invocation-id")
    sample_parser.add_argument("--timeout-seconds", type=float, default=3600.0)

    attribution_parser = subparsers.add_parser(
        "legacy-stage-attribution",
        help="diagnostically time each exact legacy command with fail-fast order",
    )
    attribution_parser.add_argument("output_root", type=Path)
    attribution_parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
    )
    attribution_parser.add_argument("--invocation-id")

    summary_parser = subparsers.add_parser(
        "legacy-baseline-summary",
        help="reduce at least five paired cold/warm legacy samples",
    )
    summary_parser.add_argument("output_root", type=Path)
    summary_parser.add_argument("sample_paths", type=Path, nargs="+")
    summary_parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)

    phase0_parser = subparsers.add_parser(
        "phase0-baseline-report",
        help="close total, stage, collection, and node-level Phase-0 evidence",
    )
    phase0_parser.add_argument("output_root", type=Path)
    phase0_parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    phase0_parser.add_argument(
        "--legacy-summary",
        type=Path,
        required=True,
    )
    phase0_parser.add_argument(
        "--stage-attribution",
        type=Path,
        required=True,
    )
    phase0_parser.add_argument(
        "--shadow-coverage",
        type=Path,
        action="append",
        required=True,
    )
    phase0_parser.add_argument(
        "--pytest-observation",
        type=Path,
        required=True,
    )
    phase0_parser.add_argument(
        "--observation-binding",
        type=Path,
        required=True,
    )
    return parser


def _config_summary(config: TestGateConfig) -> dict[str, object]:
    return {
        "schema_id": config.schema_id,
        "config_digest": config.digest,
        "worker_hard_max": config.worker_hard_max,
        "supported_profiles": list(config.supported_profiles),
        "forbidden_dispatch_profiles": list(config.forbidden_dispatch_profiles),
        "stage_order": [stage.id for stage in config.stages],
        "operator_evidence": {
            "repository_plane_only": config.evidence_policy.repository_plane_only,
            "requires_checkout_external_output_root": (
                config.evidence_policy.requires_checkout_external_output_root
            ),
            "product_state_writes": config.evidence_policy.product_state_writes,
        },
        "pytest_contract": {
            "marker_expression": config.pytest_contract.marker_expression,
            "allowed_non_live_markers": list(
                config.pytest_contract.allowed_non_live_markers
            ),
            "forbidden_non_live_markers": list(
                config.pytest_contract.forbidden_non_live_markers
            ),
            "architecture_scenario_marker": (
                config.pytest_contract.architecture_scenario_marker
            ),
        },
    }


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(payload) + b"\n")


def _invocation_id(value: str | None) -> str:
    return value or uuid.uuid4().hex


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        config = load_config(arguments.config)
        if arguments.command == "inspect-config":
            _emit(_config_summary(config))
            return 0
        if arguments.command == "source-identity":
            identity = collect_source_identity(arguments.repo_root)
            _emit({"source_identity": identity.as_dict(), "digest": identity.digest})
            return 0
        if arguments.command == "validate-output-root":
            validated = validate_new_output_root(
                arguments.repo_root,
                arguments.output_root,
            )
            _emit(
                {
                    "output_root": str(validated),
                    "valid": True,
                    "operator_evidence_only": True,
                }
            )
            return 0
        if arguments.command == "validate-profile":
            profile = validate_dispatch_profile(config, arguments.profile_id)
            _emit(
                {
                    "profile_id": profile.id,
                    "valid": True,
                    "authoritative": profile.authoritative,
                    "admission_eligible": profile.admission_eligible,
                    "live_eligible": profile.live_eligible,
                    "summary": profile.summary,
                }
            )
            return 0
        if arguments.command == "focused-diagnostic":
            print(
                "NON-AUTHORITATIVE DIAGNOSTIC: no merge, mainline, "
                "architecture-admission, AOX, live-campaign, or scientific-"
                "evidence authority.",
                file=sys.stderr,
            )
            result = run_focused_diagnostic(
                repo_root=arguments.repo_root,
                output_root=arguments.output_root,
                config=config,
                invocation_id=_invocation_id(arguments.invocation_id),
                lint_paths=arguments.lint_path,
                pytest_paths=arguments.pytest_path,
                node_ids=arguments.node_id,
                contract_groups=arguments.contract_group,
            )
            _emit(
                {
                    "profile_id": "focused_diagnostic",
                    "output_root": str(result.output_root),
                    "plan_digest": result.plan["self_digest"],
                    "receipt_digest": result.receipt["self_digest"],
                    "terminal_status": result.terminal_status,
                    "authoritative": False,
                    "admission_eligible": False,
                    "live_eligible": False,
                    "summary": (
                        "NON-AUTHORITATIVE diagnostic feedback only; "
                        "run scripts/check-mainline.sh for merge authority"
                    ),
                }
            )
            return 0 if result.terminal_status == "pass" else 1
        if arguments.command == "replay-corpus":
            corpus = load_replay_corpus(arguments.corpus)
            print(
                "NON-AUTHORITATIVE REPLAY CORPUS: this twenty-case evidence "
                "cannot grant merge, architecture-admission, AOX, live, or "
                "scientific authority.",
                file=sys.stderr,
            )
            result = run_focused_diagnostic(
                repo_root=arguments.repo_root,
                output_root=arguments.output_root,
                config=config,
                invocation_id=_invocation_id(arguments.invocation_id),
                node_ids=corpus.proof_node_ids,
            )
            _emit(
                {
                    "profile_id": "focused_diagnostic",
                    "corpus_id": corpus.corpus_id,
                    "corpus_digest": corpus.self_digest,
                    "case_count": len(corpus.cases),
                    "proof_node_count": len(corpus.proof_node_ids),
                    "output_root": str(result.output_root),
                    "plan_digest": result.plan["self_digest"],
                    "receipt_digest": result.receipt["self_digest"],
                    "terminal_status": result.terminal_status,
                    "authoritative": False,
                    "admission_eligible": False,
                    "live_eligible": False,
                }
            )
            return 0 if result.terminal_status == "pass" else 1
        if arguments.command == "affected-scope-diagnostic":
            print(
                "NON-AUTHORITATIVE AFFECTED-SCOPE DIAGNOSTIC: no merge, "
                "mainline, architecture-admission, AOX, live-campaign, or "
                "scientific-evidence authority.",
                file=sys.stderr,
            )
            result = run_affected_scope_diagnostic(
                repo_root=arguments.repo_root,
                output_root=arguments.output_root,
                config=config,
                invocation_id=_invocation_id(arguments.invocation_id),
                base_ref=arguments.base_ref,
                map_path=arguments.map,
            )
            selection = result.plan["diagnostic_selection"]
            _emit(
                {
                    "profile_id": "affected_scope_diagnostic",
                    "output_root": str(result.output_root),
                    "plan_digest": result.plan["self_digest"],
                    "receipt_digest": result.receipt["self_digest"],
                    "terminal_status": result.terminal_status,
                    "changed_path_count": len(
                        selection["input"]["changed_paths"]
                    ),
                    "matched_rules": selection["matched_rules"],
                    "unknown_paths": selection["unknown_paths"],
                    "fallback_complete_safe": selection[
                        "fallback_complete_safe"
                    ],
                    "frontend": selection["frontend"],
                    "authoritative": False,
                    "admission_eligible": False,
                    "live_eligible": False,
                    "summary": (
                        "NON-AUTHORITATIVE affected-scope feedback only; "
                        "run scripts/check-mainline.sh for merge authority"
                    ),
                }
            )
            return 0 if result.terminal_status == "pass" else 1
        if arguments.command == "verify-diagnostic":
            current_source = collect_source_identity(arguments.repo_root)
            plan, receipt = verify_diagnostic_output(
                plan_path=arguments.plan_path,
                receipt_path=arguments.receipt_path,
                current_source_identity_digest=current_source.digest,
            )
            print(
                "VERIFIED NON-AUTHORITATIVE DIAGNOSTIC: this evidence grants "
                "no merge, admission, AOX, live, or scientific authority.",
                file=sys.stderr,
            )
            _emit(
                {
                    "profile_id": receipt["profile_id"],
                    "plan_digest": plan["self_digest"],
                    "receipt_digest": receipt["self_digest"],
                    "terminal_status": receipt["terminal_status"],
                    "valid": True,
                    "authoritative": False,
                    "admission_eligible": False,
                    "live_eligible": False,
                }
            )
            return 0 if receipt["terminal_status"] == "pass" else 1
        if arguments.command == "plan-mainline-shadow":
            print(
                "SHADOW MAINLINE CANDIDATE: scripts/check-mainline.sh remains "
                "the current authority; this plan grants no merge, admission, "
                "AOX, live, or scientific authority.",
                file=sys.stderr,
            )
            result = run_authoritative_shadow_plan(
                repo_root=arguments.repo_root,
                output_root=arguments.output_root,
                config=config,
                invocation_id=_invocation_id(arguments.invocation_id),
                resource_manifest_path=arguments.resource_manifest,
                workers=arguments.workers,
            )
            _emit(
                {
                    "profile_id": "mainline_authoritative",
                    "output_root": str(result.output_root),
                    "plan_digest": result.plan["self_digest"],
                    "manifest_digest": result.manifest["self_digest"],
                    "general_nodes": len(
                        result.plan["collections"]["general"]["nodes"]
                    ),
                    "qualification_nodes": len(
                        result.manifest["planned_deselected_nodes"]
                    ),
                    "residual_nodes": len(result.manifest["selected_nodes"]),
                    "authoritative": False,
                    "current_authoritative_entry": (
                        "scripts/check-mainline.sh"
                    ),
                }
            )
            return 0
        if arguments.command == "verify-mainline-plan":
            plan, manifest = verify_authoritative_plan_files(
                plan_path=arguments.plan_path,
                manifest_path=arguments.manifest_path,
                repo_root=arguments.repo_root,
                config=config,
            )
            print(
                "VERIFIED SHADOW MAINLINE PLAN: scripts/check-mainline.sh "
                "remains the current authority.",
                file=sys.stderr,
            )
            _emit(
                {
                    "profile_id": "mainline_authoritative",
                    "plan_digest": plan["self_digest"],
                    "manifest_digest": manifest["self_digest"],
                    "valid": True,
                    "authoritative": False,
                    "admission_eligible": False,
                    "live_eligible": False,
                }
            )
            return 0
        if arguments.command == "mainline_authoritative":
            selected_workers = (
                1 if arguments.forced_serial else arguments.workers
            )
            print(
                "CURRENT NON-LIVE MERGE AUTHORITY: complete mainline contract "
                f"with {'forced serial' if selected_workers == 1 else f'fixed {selected_workers} workers'}; "
                "no architecture-admission, AOX, live-campaign, or scientific-"
                "evidence authority.",
                file=sys.stderr,
            )
            result = run_authoritative_mainline(
                repo_root=arguments.repo_root,
                output_root=arguments.output_root,
                config=config,
                invocation_id=_invocation_id(arguments.invocation_id),
                resource_manifest_path=arguments.resource_manifest,
                workers=selected_workers,
            )
            _emit(
                {
                    "profile_id": "mainline_authoritative",
                    "output_root": str(result.output_root),
                    "plan_digest": result.plan["self_digest"],
                    "receipt_digest": result.receipt["self_digest"],
                    "terminal_status": result.terminal_status,
                    "authoritative": True,
                    "profile_contract_authoritative": True,
                    "admission_eligible": False,
                    "live_eligible": False,
                    "authority_domain": "authoritative_non_live_mainline",
                    "forced_serial": selected_workers == 1,
                    "workers": selected_workers,
                    "current_authoritative_entry": "scripts/check-mainline.sh",
                }
            )
            return 0 if result.terminal_status == "pass" else 1
        if arguments.command == "verify-mainline-authoritative":
            result = verify_authoritative_mainline_output(
                output_root=arguments.output_root,
                repo_root=arguments.repo_root,
                config=config,
            )
            print(
                "VERIFIED CURRENT NON-LIVE MERGE AUTHORITY: no architecture-"
                "admission, AOX, live-campaign, or scientific-evidence "
                "authority.",
                file=sys.stderr,
            )
            _emit(
                {
                    "profile_id": "mainline_authoritative",
                    "output_root": str(result.output_root),
                    "plan_digest": result.plan["self_digest"],
                    "receipt_digest": result.receipt["self_digest"],
                    "terminal_status": result.receipt["terminal_status"],
                    "valid": True,
                    "authoritative": True,
                    "profile_contract_authoritative": True,
                    "admission_eligible": False,
                    "live_eligible": False,
                    "authority_domain": "authoritative_non_live_mainline",
                    "current_authoritative_entry": "scripts/check-mainline.sh",
                }
            )
            return 0
        if arguments.command == "run-mainline-candidate":
            selected_workers = 1 if arguments.forced_serial else arguments.workers
            print(
                "OPT-IN SHADOW CANDIDATE: "
                f"{'forced serial' if selected_workers == 1 else f'fixed {selected_workers} workers'}; "
                "scripts/check-mainline.sh remains the only authoritative "
                "merge entry.",
                file=sys.stderr,
            )
            result = run_authoritative_shadow_candidate(
                repo_root=arguments.repo_root,
                output_root=arguments.output_root,
                config=config,
                invocation_id=_invocation_id(arguments.invocation_id),
                resource_manifest_path=arguments.resource_manifest,
                workers=selected_workers,
            )
            _emit(
                {
                    "profile_id": "mainline_authoritative",
                    "output_root": str(result.output_root),
                    "plan_digest": result.plan["self_digest"],
                    "receipt_digest": result.receipt["self_digest"],
                    "terminal_status": result.terminal_status,
                    "authoritative": False,
                    "forced_serial": selected_workers == 1,
                    "workers": selected_workers,
                    "current_authoritative_entry": (
                        "scripts/check-mainline.sh"
                    ),
                }
            )
            return 0 if result.terminal_status == "pass" else 1
        if arguments.command == "verify-mainline-receipt":
            result = verify_authoritative_candidate_output(
                output_root=arguments.output_root,
                repo_root=arguments.repo_root,
                config=config,
            )
            _emit(
                {
                    "profile_id": "mainline_authoritative",
                    "output_root": str(result.output_root),
                    "plan_digest": result.plan["self_digest"],
                    "receipt_digest": result.receipt["self_digest"],
                    "terminal_status": result.receipt["terminal_status"],
                    "valid": True,
                    "authoritative": False,
                    "admission_eligible": False,
                    "live_eligible": False,
                }
            )
            return 0
        if arguments.command == "optimized-sample":
            selected_workers = (
                1 if arguments.forced_serial else arguments.workers
            )
            result = run_optimized_sample(
                repo_root=arguments.repo_root,
                output_root=arguments.output_root,
                config=config,
                invocation_id=_invocation_id(arguments.invocation_id),
                sample_kind=arguments.sample_kind,
                sample_index=arguments.sample_index,
                workers=selected_workers,
                resource_manifest_path=arguments.resource_manifest,
            )
            _emit(
                {
                    "output_root": str(result.candidate.output_root),
                    "sample_digest": result.document["self_digest"],
                    "sample_kind": arguments.sample_kind,
                    "sample_index": arguments.sample_index,
                    "workers": selected_workers,
                    "functional_green": result.functional_green,
                    "terminal_status": result.candidate.terminal_status,
                    "authoritative": False,
                }
            )
            return 0 if result.functional_green else 1
        if arguments.command == "optimized-summary":
            document = build_optimized_benchmark_summary(
                sample_paths=arguments.sample_paths,
                legacy_summary_path=arguments.legacy_summary,
            )
            sys.stdout.buffer.write(canonical_document_bytes(document))
            return (
                0
                if document["baseline_comparison"]["threshold_met"]
                else 1
            )
        if arguments.command == "execute-general-plan":
            plan, manifest = verify_authoritative_plan_files(
                plan_path=arguments.plan_path,
                manifest_path=arguments.manifest_path,
                repo_root=arguments.repo_root,
                config=config,
                ambient_environment=os.environ,
                expected_authoritative=arguments.authoritative_mainline,
            )
            merged = execute_general_partitions(
                repo_root=arguments.repo_root,
                output_root=arguments.plan_path.resolve(strict=True).parent,
                plan=plan,
                general_manifest=manifest,
                resource_manifest_path=arguments.resource_manifest,
                config=config,
                environment=os.environ,
            )
            _emit(
                {
                    "invocation_id": plan["invocation_id"],
                    "observation_digest": merged["self_digest"],
                    "workers": plan["worker_policy"]["workers"],
                    "terminal_status": "pass",
                }
            )
            return 0
        if arguments.command == "shadow-collect":
            result = run_shadow_collection(
                repo_root=arguments.repo_root,
                output_root=arguments.output_root,
                config=config,
                invocation_id=_invocation_id(arguments.invocation_id),
            )
            _emit(
                {
                    "output_root": str(result.output_root),
                    "source_identity_digest": result.source_identity.digest,
                    "general_nodes": len(result.general.nodes),
                    "qualification_harness_nodes": len(
                        result.qualification_harness.nodes
                    ),
                    "qualification_scenario_nodes": len(
                        result.qualification_scenarios.nodes
                    ),
                    "distinct_required_nodes": len(
                        result.coverage_document["distinct_required_nodes"]
                    ),
                    "structural_duplicates": len(
                        result.coverage_document["structural_duplicates"]
                    ),
                    "terminal_status": result.coverage_document["terminal_status"],
                    "authoritative": False,
                }
            )
            return 0
        if arguments.command == "legacy-sample":
            result = run_legacy_sample(
                repo_root=arguments.repo_root,
                output_root=arguments.output_root,
                invocation_id=_invocation_id(arguments.invocation_id),
                sample_kind=arguments.sample_kind,
                sample_index=arguments.sample_index,
                timeout_seconds=arguments.timeout_seconds,
            )
            _emit(
                {
                    "output_root": str(result.output_root),
                    "sample_digest": result.document["self_digest"],
                    "duration_ns": result.document["process_result"]["duration_ns"],
                    "functional_green": result.functional_green,
                    "authoritative_entry_executed": False,
                    "comparison_entry": "scripts/check-mainline-legacy.sh",
                }
            )
            return 0 if result.functional_green else 1
        if arguments.command == "legacy-stage-attribution":
            result = run_legacy_stage_attribution(
                repo_root=arguments.repo_root,
                output_root=arguments.output_root,
                invocation_id=_invocation_id(arguments.invocation_id),
                config=config,
            )
            _emit(
                {
                    "output_root": str(result.output_root),
                    "attribution_digest": result.document["self_digest"],
                    "terminal_status": result.terminal_status,
                    "authoritative": False,
                }
            )
            return 0 if result.terminal_status == "pass" else 1
        if arguments.command == "legacy-baseline-summary":
            document = build_legacy_baseline_summary(arguments.sample_paths)
            evidence_root = create_new_output_root(
                arguments.repo_root,
                arguments.output_root,
            )
            summary_path = evidence_root / "legacy-baseline-summary.json"
            publish_no_replace(summary_path, canonical_document_bytes(document))
            _emit(
                {
                    "output_root": str(evidence_root),
                    "summary_path": str(summary_path),
                    "summary_digest": document["self_digest"],
                    "statistics": document["statistics"],
                }
            )
            return 0
        if arguments.command == "phase0-baseline-report":
            document = build_phase0_baseline_report(
                legacy_summary_path=arguments.legacy_summary,
                stage_attribution_path=arguments.stage_attribution,
                shadow_coverage_paths=arguments.shadow_coverage,
                pytest_observation_path=arguments.pytest_observation,
                observation_binding_path=arguments.observation_binding,
            )
            evidence_root = create_new_output_root(
                arguments.repo_root,
                arguments.output_root,
            )
            report_path = evidence_root / "phase0-baseline-report.json"
            publish_no_replace(report_path, canonical_document_bytes(document))
            _emit(
                {
                    "output_root": str(evidence_root),
                    "report_path": str(report_path),
                    "report_digest": document["self_digest"],
                    "source_identity_digest": document[
                        "source_identity_digest"
                    ],
                    "cold_median_ns": document["critical_path_assessment"][
                        "cold_median_ns"
                    ],
                    "warm_median_ns": document["critical_path_assessment"][
                        "warm_median_ns"
                    ],
                    "duplicate_node_cost": document["duplicate_node_cost"],
                }
            )
            return 0
    except (
        AffectedScopeError,
        AuthoritativePlanError,
        AuthoritativeRunnerError,
        BenchmarkError,
        ConfigError,
        DiagnosticError,
        GeneralPartitionError,
        ReplayCorpusError,
        ResourceManifestError,
        ShadowCollectionError,
        ShadowCoverageError,
        SourceIdentityError,
        TestGateRunnerError,
    ) as exc:
        print(f"test-gate error: {exc}", file=sys.stderr)
        return 2
    raise AssertionError(f"unhandled command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
