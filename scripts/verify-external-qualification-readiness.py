#!/usr/bin/env python3
"""Generate and independently verify EnzymeDesign's deterministic readiness proof."""

from __future__ import annotations

import argparse
from datetime import UTC
from datetime import datetime
import json
import os
from pathlib import Path

from enzymedesign_distribution import OPTIONAL_PROFILES
from enzymedesign_distribution import ExternalQualificationReadinessCoordinator
from enzymedesign_distribution import QualificationDisclosureMatrix
from enzymedesign_distribution import RecordingQualificationProbeBackend
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from openzyme_contracts import verify_external_qualification_readiness


FORBIDDEN_CREDENTIAL_ENV = (
    "OPENAI_API_KEY",
    "OPENZYME_LLM_API_KEY",
    "TAVILY_API_KEY",
    "MICU_API_KEY",
    "SSH_AUTH_SOCK",
    "SSH_AGENT_PID",
    "OPENZYME_HPC_RUNNER_CONFIG",
    "HPC_RUNNER_CONFIG",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic external qualification readiness only."
    )
    parser.add_argument("output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "0":
        raise SystemExit("OPENZYME_ALLOW_LIVE must be exactly 0")
    present = [name for name in FORBIDDEN_CREDENTIAL_ENV if os.environ.get(name)]
    if present:
        raise SystemExit(
            "credential-bearing environment is forbidden in readiness: "
            + ", ".join(sorted(present))
        )
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"readiness output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    observed = datetime.now(tz=UTC).replace(microsecond=0)
    observed_at = observed.isoformat()
    plan = build_enzymedesign_external_qualification_plan(
        plan_id=f"enzymedesign.readiness.{observed.strftime('%Y%m%dT%H%M%SZ')}",
        created_at=observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    backend = RecordingQualificationProbeBackend(units=plan.units)
    report = ExternalQualificationReadinessCoordinator(
        probe=backend,
        negative_fixtures=backend,
    ).execute(plan, observed_at=observed_at)
    verify_external_qualification_readiness(
        plan,
        report,
        verified_at=observed_at,
    )
    matrix = QualificationDisclosureMatrix.create(plan=plan, report=report)
    document = {
        "schema_version": "enzymedesign_external_qualification_readiness_bundle@1",
        "claim": "ready_non_live",
        "all_external_systems_real_environment_verified": False,
        "all_external_software_actually_executed": False,
        "all_targets_qualified": False,
        "production_cutover_complete": False,
        "external_effect_performed": False,
        "credential_material_accessed": False,
        "fallback_performed": False,
        "plan": plan.to_dict(),
        "report": report.to_dict(),
        "disclosure_matrix": matrix.to_dict(),
        "summary": {
            "profile_count": len(plan.profiles),
            "unit_count": len(plan.units),
            "receipt_count": len(report.receipts),
            "failure_count": len(report.failures),
            "dispatch_count": sum(backend.dispatch_count.values()),
            "reconcile_count": sum(backend.reconcile_count.values()),
            "negative_tests": list(backend.negative_tests_exercised),
        },
    }
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"readiness_report={output}")
    print(f"plan_digest={plan.plan_digest}")
    print(f"report_digest={report.report_digest}")
    print(f"matrix_digest={matrix.matrix_digest}")
    print(f"units={len(plan.units)}")
    print("external_effect_performed=false")
    print("credential_material_accessed=false")
    print("fallback_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
