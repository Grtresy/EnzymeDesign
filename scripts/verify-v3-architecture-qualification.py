#!/usr/bin/env python3
"""Pure CLI wrapper around the canonical architecture report verifier."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationReportError,
)
from openzyme_host_api.architecture_qualification import (
    verify_architecture_qualification_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts/v3_architecture_qualification.py"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Purely verify one canonical V3 architecture report."
    )
    parser.add_argument("report_path", type=Path)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = arguments.repo_root.resolve(strict=True)
    try:
        verification = verify_architecture_qualification_report(
            arguments.report_path,
            repo_root=root,
            runner_path=root / "scripts/v3_architecture_qualification.py",
        )
    except (ArchitectureQualificationReportError, OSError) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "valid": False,
                },
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "admission_eligible": verification.admission_eligible,
                "payload_digest": verification.payload_digest,
                "rejection_reasons": list(verification.rejection_reasons),
                "source_commit": verification.source_commit,
                "valid": True,
            },
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
