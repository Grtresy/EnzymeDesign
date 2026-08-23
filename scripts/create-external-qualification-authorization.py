#!/usr/bin/env python3
"""Materialize one exact durable Batch 1 qualification authorization."""

from __future__ import annotations

import argparse
from datetime import UTC
from datetime import datetime
import json
import os
from pathlib import Path

from enzymedesign_distribution import QUALIFICATION_STATE_ROOT_ENV
from enzymedesign_distribution import QualificationOperatorStateLayout
from openzyme_contracts import ExternalQualificationOccurrenceAuthorization
from test_gate.source import collect_source_identity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a durable one-shot Batch 1 qualification authorization."
    )
    parser.add_argument("post_preparation_packet", type=Path)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--authorized-at")
    return parser


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return payload


def _write_private_file(path: Path, payload: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise SystemExit("qualification authorization already exists")
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
    raw_root = os.environ.get(QUALIFICATION_STATE_ROOT_ENV)
    if not raw_root:
        raise SystemExit(f"{QUALIFICATION_STATE_ROOT_ENV} is required")
    layout = QualificationOperatorStateLayout.open(Path(raw_root))
    packet = _load_object(args.post_preparation_packet.resolve())
    source = collect_source_identity(Path(__file__).resolve().parents[1])
    dry_plan_digest = packet.get("batch_1_qualification_dry_plan_digest")
    if (
        packet.get("schema_version")
        != "enzymedesign_post_preparation_operator_packet@1"
        or packet.get("claim") != "prepared_not_qualified"
        or packet.get("source_identity_digest") != source.digest
        or not isinstance(dry_plan_digest, str)
        or packet.get("qualified") is not False
        or packet.get("cutover") is not False
        or packet.get("fallback_performed") is not False
    ):
        raise SystemExit("post-preparation packet is not exact current source evidence")
    authorization = ExternalQualificationOccurrenceAuthorization.create(
        authorization_id=args.authorization_id,
        dry_plan_digest=dry_plan_digest,
        batch_id="batch-1",
        operator_id=args.operator_id,
        authorized_at=args.authorized_at or datetime.now(tz=UTC).isoformat(),
    )
    output = layout.root / f"qualification-authorization-{args.authorization_id}.json"
    _write_private_file(output, authorization.to_dict())
    print(f"authorization={output}")
    print(f"authorization_digest={authorization.authorization_digest}")
    print("authority_mode=durable_one_shot")
    print("external_effect_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
