#!/usr/bin/env python3
"""Materialize an operator-approved exact preparation authorization object."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from openzyme_contracts import ExternalIdentityPreparationOccurrenceAuthorization


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a canonical Batch 1 preparation authorization."
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--preparation-plan-digest", required=True)
    parser.add_argument("--batch-id", required=True, choices=("batch-1",))
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--valid-from", required=True)
    parser.add_argument("--valid-until", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "0":
        raise SystemExit("authorization creation requires OPENZYME_ALLOW_LIVE=0")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"authorization output already exists: {output}")
    authorization = ExternalIdentityPreparationOccurrenceAuthorization.create(
        authorization_id=args.authorization_id,
        preparation_plan_digest=args.preparation_plan_digest,
        batch_id=args.batch_id,
        operator_id=args.operator_id,
        valid_from=args.valid_from,
        valid_until=args.valid_until,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(authorization.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"authorization={output}")
    print(f"authorization_digest={authorization.authorization_digest}")
    print("external_effect_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
