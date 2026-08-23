#!/usr/bin/env python3
"""Create one durable authorization for an exact helper deployment plan."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentAuthorization
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentPlan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--operator-id", required=True)
    args = parser.parse_args()
    plan = WorkspaceRuntimeDeploymentPlan.from_dict(
        json.loads(args.plan.read_text(encoding="utf-8"))
    )
    authorization = WorkspaceRuntimeDeploymentAuthorization.create(
        authorization_id=args.authorization_id,
        plan_digest=plan.plan_digest,
        operator_id=args.operator_id,
        installer_identity=str(plan.installer_identity),
        privilege_mechanism=str(plan.privilege_mechanism),
        rollback_owner=str(plan.rollback_owner),
    )
    encoded = (
        json.dumps(authorization.to_dict(), indent=2, sort_keys=True) + "\n"
    ).encode()
    descriptor = os.open(
        args.output.resolve(),
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(f"authorization_digest={authorization.authorization_digest}")
    print("live_effect_authorized=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
