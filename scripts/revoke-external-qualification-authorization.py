#!/usr/bin/env python3
"""Explicitly revoke one durable qualification authorization."""

from __future__ import annotations

import argparse
from datetime import UTC
from datetime import datetime
import json
import os
from pathlib import Path

from enzymedesign_distribution import QUALIFICATION_STATE_ROOT_ENV
from enzymedesign_distribution import QualificationOperatorStateLayout
from openzyme_contracts import ExternalQualificationAuthorizationRevocation
from openzyme_contracts import ExternalQualificationOccurrenceAuthorization


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Revoke one exact durable Batch 1 qualification authorization."
    )
    parser.add_argument("authorization", type=Path)
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--reason-code", required=True)
    parser.add_argument("--revoked-at")
    return parser


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return payload


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "0":
        raise SystemExit("revocation creation requires OPENZYME_ALLOW_LIVE=0")
    raw_root = os.environ.get(QUALIFICATION_STATE_ROOT_ENV)
    if not raw_root:
        raise SystemExit(f"{QUALIFICATION_STATE_ROOT_ENV} is required")
    layout = QualificationOperatorStateLayout.open(Path(raw_root))
    authorization = ExternalQualificationOccurrenceAuthorization.from_dict(
        _load_object(args.authorization.resolve())
    )
    if authorization.operator_id != args.operator_id:
        raise SystemExit("revocation operator does not match authorization operator")
    revocation = ExternalQualificationAuthorizationRevocation.create(
        revocation_id=f"revocation.{authorization.authorization_id}",
        authorization_digest=authorization.authorization_digest,
        operator_id=args.operator_id,
        revoked_at=args.revoked_at or datetime.now(tz=UTC).isoformat(),
        reason_code=args.reason_code,
    )
    suffix = authorization.authorization_digest.removeprefix("sha256:")
    output = layout.private_evidence_root / f"qualification-revocation-{suffix}.json"
    if output.exists() or output.is_symlink():
        raise SystemExit("qualification authorization already has revocation evidence")
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(
            descriptor,
            (json.dumps(revocation.to_dict(), indent=2, sort_keys=True) + "\n").encode(),
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(f"revocation={output}")
    print(f"revocation_digest={revocation.revocation_digest}")
    print("external_effect_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
