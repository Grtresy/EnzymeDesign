#!/usr/bin/env python3
"""Explicitly revoke one durable preparation authorization."""

from __future__ import annotations

import argparse
from datetime import UTC
from datetime import datetime
import json
import os
from pathlib import Path
import stat

from enzymedesign_distribution import QUALIFICATION_STATE_ROOT_ENV
from enzymedesign_distribution import QualificationOperatorStateLayout
from openzyme_contracts import ExternalIdentityPreparationAuthorizationRevocation
from openzyme_contracts import ExternalIdentityPreparationOccurrenceAuthorization


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Revoke one exact durable Batch 1 preparation authorization."
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


def _ensure_private_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise SystemExit("protected evidence directory ownership or mode is unsafe")
        return
    path.mkdir(mode=0o700, parents=False)


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE") != "0":
        raise SystemExit("revocation creation requires OPENZYME_ALLOW_LIVE=0")
    raw_root = os.environ.get(QUALIFICATION_STATE_ROOT_ENV)
    if not raw_root:
        raise SystemExit(f"{QUALIFICATION_STATE_ROOT_ENV} is required")
    layout = QualificationOperatorStateLayout.open(Path(raw_root))
    authorization = ExternalIdentityPreparationOccurrenceAuthorization.from_dict(
        _load_object(args.authorization.resolve())
    )
    if args.operator_id != authorization.operator_id:
        raise SystemExit("revocation operator does not match authorization operator")
    revoked_at = args.revoked_at or datetime.now(tz=UTC).isoformat()
    revocation = ExternalIdentityPreparationAuthorizationRevocation.create(
        revocation_id=f"revocation.{authorization.authorization_id}",
        authorization_digest=authorization.authorization_digest,
        operator_id=args.operator_id,
        revoked_at=revoked_at,
        reason_code=args.reason_code,
    )
    _ensure_private_directory(layout.private_evidence_root)
    suffix = authorization.authorization_digest.removeprefix("sha256:")
    output = layout.private_evidence_root / f"preparation-revocation-{suffix}.json"
    if output.exists() or output.is_symlink():
        raise SystemExit("preparation authorization already has revocation evidence")
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(
            descriptor,
            (json.dumps(revocation.to_dict(), indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
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
