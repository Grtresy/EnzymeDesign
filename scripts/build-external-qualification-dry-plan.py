#!/usr/bin/env python3
"""Build a secret-safe, no-effect EnzymeDesign external qualification packet."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path

from enzymedesign_distribution import OPTIONAL_PROFILES
from enzymedesign_distribution import (
    EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS,
)
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from enzymedesign_distribution import load_safe_identity_snapshot
from enzymedesign_distribution import load_operator_identity_resolution_selections
from enzymedesign_distribution import qualification_plan_bundle
from test_gate.source import collect_source_identity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build external qualification discovery and dry plans only."
    )
    parser.add_argument("safe_snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--decision-selections",
        type=Path,
        help="Secret-safe operator selections; still does not authorize effects.",
    )
    parser.add_argument(
        "--exact-prepared-locators",
        action="store_true",
        help=(
            "Rebuild from a prepared snapshot using the exact live-qualification "
            "locator mapping, including no credential locator for local-only Git/LFS."
        ),
    )
    return parser


def _readiness_credential_locator_ids(
    *,
    exact_prepared_locators: bool,
) -> dict[str, str | None] | None:
    if not exact_prepared_locators:
        return None
    return dict(EXACT_EXTERNAL_QUALIFICATION_CREDENTIAL_LOCATORS)


def _locator_binding_mode(*, exact_prepared_locators: bool) -> str:
    return "exact_prepared" if exact_prepared_locators else "nonlive_initial"


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "0":
        raise SystemExit("OPENZYME_ALLOW_LIVE must be exactly 0 for dry-plan mode")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"dry-plan output already exists: {output}")
    repo_root = Path(__file__).resolve().parents[1]
    source = collect_source_identity(repo_root)
    snapshot = replace(
        load_safe_identity_snapshot(args.safe_snapshot.resolve()),
        source_digest=source.digest,
    )
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id=f"qualification.readiness.{snapshot.snapshot_id}",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
        credential_locator_ids=_readiness_credential_locator_ids(
            exact_prepared_locators=args.exact_prepared_locators,
        ),
    )
    document = qualification_plan_bundle(
        readiness_plan=readiness,
        snapshot=snapshot,
        selection_set=(
            None
            if args.decision_selections is None
            else load_operator_identity_resolution_selections(
                args.decision_selections.resolve()
            )
        ),
    )
    document["locator_binding_mode"] = _locator_binding_mode(
        exact_prepared_locators=args.exact_prepared_locators
    )
    document["source_identity"] = source.as_dict()
    document["source_identity_digest"] = source.digest
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = document["summary"]
    print(f"operator_packet={output}")
    print(f"source_identity_digest={source.digest}")
    print(f"observations={summary['observation_count']}")
    print(f"identity_gaps={summary['gap_count']}")
    print(f"identity_decisions={summary['decision_count']}")
    print(
        "batch_1_preparation_authorizable="
        f"{str(summary['batch_1_preparation_authorizable']).lower()}"
    )
    print(
        "batch_2_preparation_authorizable="
        f"{str(summary['batch_2_preparation_authorizable']).lower()}"
    )
    print(f"batch_1_authorizable={str(summary['batch_1_authorizable']).lower()}")
    print(f"batch_2_authorizable={str(summary['batch_2_authorizable']).lower()}")
    print("live_effect_authorized=false")
    print("credential_material_accessed=false")
    print("external_effect_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
