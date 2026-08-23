#!/usr/bin/env python3
"""Materialize an operator-approved exact preparation authorization object."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat

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
    parser.add_argument("--authorized-at", required=True)
    return parser


def _write_private_file(path: Path, payload: dict[str, object]) -> None:
    parent = path.parent
    if not parent.exists():
        parent.mkdir(mode=0o700, parents=True)
    metadata = parent.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise SystemExit("authorization parent ownership or mode is unsafe")
    if path.exists() or path.is_symlink():
        raise SystemExit(f"authorization output already exists: {path}")
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "0":
        raise SystemExit("authorization creation requires OPENZYME_ALLOW_LIVE=0")
    output = args.output.resolve()
    authorization = ExternalIdentityPreparationOccurrenceAuthorization.create(
        authorization_id=args.authorization_id,
        preparation_plan_digest=args.preparation_plan_digest,
        batch_id=args.batch_id,
        operator_id=args.operator_id,
        authorized_at=args.authorized_at,
    )
    _write_private_file(output, authorization.to_dict())
    print(f"authorization={output}")
    print(f"authorization_digest={authorization.authorization_digest}")
    print("external_effect_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
