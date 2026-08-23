#!/usr/bin/env python3
"""Create only the protected EnzymeDesign qualification root/layout skeleton."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from enzymedesign_distribution import QUALIFICATION_STATE_ROOT_ENV
from enzymedesign_distribution import QualificationOperatorStateLayout


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap the protected qualification root without credentials."
    )
    parser.add_argument(
        "--confirm-layout-id",
        required=True,
        choices=("qualification.operator-state.primary",),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "0":
        raise SystemExit("bootstrap requires OPENZYME_ALLOW_LIVE=0")
    raw_root = os.environ.get(QUALIFICATION_STATE_ROOT_ENV)
    if not raw_root:
        raise SystemExit(f"{QUALIFICATION_STATE_ROOT_ENV} is required")
    root = Path(raw_root)
    layout = QualificationOperatorStateLayout.bootstrap(
        root,
        layout_id=args.confirm_layout_id,
    )
    print(
        json.dumps(
            {
                "schema_version": "enzymedesign_qualification_bootstrap_receipt@1",
                "layout": layout.safe_identity(),
                "credential_bundle_created": False,
                "external_effect_performed": False,
                "live_effect_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
