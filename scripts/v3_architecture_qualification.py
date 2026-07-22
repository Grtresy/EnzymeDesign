#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationReportError,
)
from openzyme_host_api.architecture_qualification_runner import run_qualification


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = Path(__file__).resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the non-live OpenZyme V3 architecture qualification matrix."
    )
    parser.add_argument(
        "mode",
        choices=("admission", "diagnostic", "premerge_subset"),
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="New absolute no-replace directory outside the checkout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    command = [sys.executable, str(RUNNER_PATH), *(argv or sys.argv[1:])]
    try:
        result = run_qualification(
            repo_root=REPO_ROOT,
            runner_path=RUNNER_PATH,
            mode=arguments.mode,
            output_directory=arguments.output_dir,
            command=command,
        )
    except ArchitectureQualificationReportError as exc:
        print(
            json.dumps(
                {
                    "error_code": exc.code,
                    "message": str(exc),
                    "report_path": None,
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
                "admission_eligible": result.report.payload["admission_eligible"],
                "payload_digest": result.report.payload_digest,
                "rejection_reasons": result.report.payload["rejection_reasons"],
                "report_path": str(result.report_path),
            },
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return result.process_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
