#!/usr/bin/env python3
"""Create one effect-free, source-bound Diannan helper deployment plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

from enzymedesign_distribution import ProtectedQualificationCredentialBundleResolver
from enzymedesign_distribution import QUALIFICATION_STATE_ROOT_ENV
from enzymedesign_distribution import QualificationOperatorStateLayout
from openzyme_contracts import canonical_sha256_digest
from openzyme_hpc_ssh import OpenSshQualificationState
from openzyme_hpc_ssh import SubprocessOpenSshQualificationCommandPort
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentPlan
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentScope
from openzyme_hpc_ssh import WorkspaceRuntimeDestinationState
from openzyme_hpc_ssh import workspace_runtime_source_bytes
from test_gate.source import collect_source_identity


HPC_LOCATOR = "credential.hpc.diannan.qualification"
TARGET_LOGIN = "grtresy"
TARGET_HOME = "/home/grtresy"
DESTINATION = f"{TARGET_HOME}/.local/libexec/openzyme-workspace-runtime"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    return parser


def _write_private(path: Path, payload: dict[str, object]) -> None:
    if not path.is_absolute() or path.parent.stat().st_mode & 0o777 != 0o700:
        raise ValueError("deployment plan output parent must be absolute and 0700")
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or path.read_bytes() != encoded
        ):
            raise ValueError("existing deployment plan output conflicts")
        return
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _preflight(state: OpenSshQualificationState) -> dict[str, str]:
    script = f"""set -eu
login=$(id -un)
uid=$(id -u)
gid=$(id -g)
home=$(getent passwd "$uid" | cut -d: -f6)
group=$(id -gn)
printf 'LOGIN=%s\nUID=%s\nGID=%s\nGROUP=%s\nHOME=%s\n' "$login" "$uid" "$gid" "$group" "$home"
for name in home local libexec; do
  case "$name" in
    home) path="$home" ;;
    local) path="$home/.local" ;;
    libexec) path="$home/.local/libexec" ;;
  esac
  if test -L "$path"; then kind=symlink; owner=none; mode=none; writable=0
  elif test -d "$path"; then kind=directory; owner=$(stat -c '%U:%G' "$path"); mode=$(stat -c '%a' "$path"); if test -w "$path"; then writable=1; else writable=0; fi
  elif test -e "$path"; then kind=other; owner=none; mode=none; writable=0
  else kind=missing; owner=none; mode=none; parent=$(dirname "$path"); if test -d "$parent" && test -w "$parent"; then writable=1; else writable=0; fi
  fi
  printf 'PATH_%s=%s|%s|%s|%s\n' "$name" "$kind" "$owner" "$mode" "$writable"
done
destination={DESTINATION!r}
if test -L "$destination"; then printf 'DESTINATION=unsafe\n'
elif test -f "$destination"; then printf 'DESTINATION=present\nDESTINATION_DIGEST=sha256:%s\n' "$(sha256sum "$destination" | cut -d' ' -f1)"
elif test -e "$destination"; then printf 'DESTINATION=unsafe\n'
else printf 'DESTINATION=missing\n'
fi
"""
    returncode, stdout, _stderr = state.run_remote(script)
    if returncode != 0:
        raise RuntimeError("workspace runtime deployment preflight failed")
    fields = dict(
        line.split("=", 1) for line in stdout.splitlines() if "=" in line
    )
    required = {
        "LOGIN",
        "UID",
        "GID",
        "GROUP",
        "HOME",
        "PATH_home",
        "PATH_local",
        "PATH_libexec",
        "DESTINATION",
    }
    if not required.issubset(fields):
        raise RuntimeError("workspace runtime deployment preflight shape drifted")
    return fields


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("OPENZYME_ALLOW_LIVE", "0") != "0":
        raise SystemExit("deployment planning requires OPENZYME_ALLOW_LIVE=0")
    raw_root = os.environ.get(QUALIFICATION_STATE_ROOT_ENV)
    if not raw_root:
        raise SystemExit(f"{QUALIFICATION_STATE_ROOT_ENV} is required")
    layout = QualificationOperatorStateLayout.open(Path(raw_root))
    material = ProtectedQualificationCredentialBundleResolver(
        layout=layout,
        allowed_locator_ids=(HPC_LOCATOR,),
    ).resolve(locator_id=HPC_LOCATOR)
    state = OpenSshQualificationState(
        credential_material=material,
        workspace_id="workspace-runtime-deployment-preflight",
        command_port=SubprocessOpenSshQualificationCommandPort(),
    )
    observed = _preflight(state)
    if (
        observed["LOGIN"] != TARGET_LOGIN
        or observed["HOME"] != TARGET_HOME
        or not observed["UID"].isdigit()
        or not observed["GID"].isdigit()
        or observed["PATH_home"] != "directory|grtresy:grtresy|700|1"
        or observed["PATH_local"]
        not in {"directory|grtresy:grtresy|700|1", "directory|grtresy:grtresy|755|1"}
        or observed["PATH_libexec"]
        not in {"missing|none|none|1", "directory|grtresy:grtresy|700|1"}
        or observed["DESTINATION"] not in {"missing", "present"}
    ):
        raise RuntimeError("blocked_deployment_authority")
    destination_state = WorkspaceRuntimeDestinationState(observed["DESTINATION"])
    destination_digest = observed.get("DESTINATION_DIGEST")
    known_hosts = Path(material.field_value("known_hosts_file")).absolute()
    host_key_digest = canonical_sha256_digest(
        {
            "known_hosts_sha256": hashlib.sha256(known_hosts.read_bytes()).hexdigest(),
            "host_alias": "Diannan",
            "ssh_port": material.field_value("ssh_port"),
        }
    )
    target_subject_digest = canonical_sha256_digest(
        {
            "schema_version": "diannan_workspace_runtime_deployment_subject@1",
            "target": "Diannan",
            "login": observed["LOGIN"],
            "uid": observed["UID"],
            "gid": observed["GID"],
            "group": observed["GROUP"],
            "home": observed["HOME"],
            "host_key_digest": host_key_digest,
            "destination": DESTINATION,
        }
    )
    source = collect_source_identity(Path(__file__).resolve().parents[1])
    helper = workspace_runtime_source_bytes()
    plan = WorkspaceRuntimeDeploymentPlan.create(
        source_identity_digest=source.digest,
        target_subject_digest=target_subject_digest,
        target_host_key_digest=host_key_digest,
        helper_build_digest="sha256:" + hashlib.sha256(helper).hexdigest(),
        helper_version="1.0.0",
        target_login=TARGET_LOGIN,
        target_home=TARGET_HOME,
        deployment_scope=WorkspaceRuntimeDeploymentScope.TARGET_PRINCIPAL_USER_LIBEXEC,
        destination_state=destination_state,
        destination_pre_digest=destination_digest,
        installer_identity="principal.grtresy.diannan",
        privilege_mechanism="direct-user-libexec-v1",
        rollback_owner="principal.grtresy.diannan",
        file_owner=TARGET_LOGIN,
        file_group=observed["GROUP"],
    )
    _write_private(args.output.resolve(), plan.to_dict())
    print(f"plan_digest={plan.plan_digest}")
    print(f"status={plan.status.value}")
    print(f"destination_state={plan.destination_state.value}")
    print("live_effect_authorized=false")
    print("fallback_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
