from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
import base64
import hashlib
from pathlib import Path
import re
import shlex
from typing import ClassVar
from typing import Mapping
from typing import Protocol

from openzyme_contracts import canonical_sha256_digest


WORKSPACE_RUNTIME_SYSTEM_DESTINATION = "/usr/local/libexec/openzyme-workspace-runtime"
WORKSPACE_RUNTIME_DEPLOYMENT_PLAN_SCHEMA = "workspace_runtime_deployment_plan@1"
WORKSPACE_RUNTIME_DEPLOYMENT_AUTHORIZATION_SCHEMA = (
    "workspace_runtime_deployment_authorization@1"
)
WORKSPACE_RUNTIME_DEPLOYMENT_RECEIPT_SCHEMA = "workspace_runtime_deployment_receipt@1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class WorkspaceRuntimeDeploymentStatus(StrEnum):
    BLOCKED_DEPLOYMENT_AUTHORITY = "blocked_deployment_authority"
    READY = "ready"


class WorkspaceRuntimeDestinationState(StrEnum):
    MISSING = "missing"
    PRESENT = "present"


class WorkspaceRuntimeDeploymentScope(StrEnum):
    TARGET_PRINCIPAL_USER_LIBEXEC = "target-principal-user-libexec-v1"
    SYSTEM_LIBEXEC = "system-libexec-v1"


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeDeploymentPlan:
    source_identity_digest: str
    target_subject_digest: str
    target_host_key_digest: str
    helper_build_digest: str
    helper_version: str
    target_login: str
    target_home: str
    deployment_scope: WorkspaceRuntimeDeploymentScope
    destination_path: str
    workspace_parent: str
    destination_state: WorkspaceRuntimeDestinationState
    destination_pre_digest: str | None
    staging_path: str
    backup_path: str
    installer_identity: str | None
    privilege_mechanism: str | None
    rollback_owner: str | None
    file_owner: str
    file_group: str
    file_mode: str
    positive_probes: tuple[str, ...]
    negative_probes: tuple[str, ...]
    live_effect_authorized: bool
    status: WorkspaceRuntimeDeploymentStatus
    plan_digest: str

    SCHEMA_VERSION: ClassVar[str] = WORKSPACE_RUNTIME_DEPLOYMENT_PLAN_SCHEMA

    @classmethod
    def create(
        cls,
        *,
        source_identity_digest: str,
        target_subject_digest: str,
        target_host_key_digest: str,
        helper_build_digest: str,
        helper_version: str,
        target_login: str,
        target_home: str,
        deployment_scope: WorkspaceRuntimeDeploymentScope,
        destination_state: WorkspaceRuntimeDestinationState,
        destination_pre_digest: str | None,
        installer_identity: str | None,
        privilege_mechanism: str | None,
        rollback_owner: str | None,
        file_owner: str | None = None,
        file_group: str | None = None,
        file_mode: str = "0755",
    ) -> "WorkspaceRuntimeDeploymentPlan":
        suffix = helper_build_digest.removeprefix("sha256:")[:24]
        destination_parent = (
            f"{target_home}/.local/libexec"
            if deployment_scope
            is WorkspaceRuntimeDeploymentScope.TARGET_PRINCIPAL_USER_LIBEXEC
            else "/usr/local/libexec"
        )
        destination_path = f"{destination_parent}/openzyme-workspace-runtime"
        workspace_parent = f"{target_home}/.local/state/openzyme-executor-workspaces"
        expected_owner = (
            target_login
            if deployment_scope
            is WorkspaceRuntimeDeploymentScope.TARGET_PRINCIPAL_USER_LIBEXEC
            else "root"
        )
        status = (
            WorkspaceRuntimeDeploymentStatus.READY
            if installer_identity and privilege_mechanism and rollback_owner
            else WorkspaceRuntimeDeploymentStatus.BLOCKED_DEPLOYMENT_AUTHORITY
        )
        values = {
            "source_identity_digest": source_identity_digest,
            "target_subject_digest": target_subject_digest,
            "target_host_key_digest": target_host_key_digest,
            "helper_build_digest": helper_build_digest,
            "helper_version": helper_version,
            "target_login": target_login,
            "target_home": target_home,
            "deployment_scope": deployment_scope,
            "destination_path": destination_path,
            "workspace_parent": workspace_parent,
            "destination_state": destination_state,
            "destination_pre_digest": destination_pre_digest,
            "staging_path": (
                f"{destination_parent}/.openzyme-workspace-runtime.stage.{suffix}"
            ),
            "backup_path": (
                f"{destination_parent}/.openzyme-workspace-runtime.backup.{suffix}"
            ),
            "installer_identity": installer_identity,
            "privilege_mechanism": privilege_mechanism,
            "rollback_owner": rollback_owner,
            "file_owner": file_owner or expected_owner,
            "file_group": file_group or expected_owner,
            "file_mode": file_mode,
            "positive_probes": (
                "version-and-build-digest",
                "exact-root-provision-verify-cleanup",
                "same-occurrence-cleanup-reconcile",
            ),
            "negative_probes": (
                "cross-root-policy-rejected-before-mutation",
                "symlink-root-rejected-before-mutation",
                "owner-and-handle-drift-rejected",
                "scheduler-command-surface-absent",
            ),
            "live_effect_authorized": False,
            "status": status,
        }
        plan = cls(**values, plan_digest="sha256:" + "0" * 64)
        return replace(plan, plan_digest=canonical_sha256_digest(plan.identity_payload))

    def __post_init__(self) -> None:
        for field_name in (
            "source_identity_digest",
            "target_subject_digest",
            "target_host_key_digest",
            "helper_build_digest",
            "plan_digest",
        ):
            if _DIGEST.fullmatch(getattr(self, field_name)) is None:
                raise ValueError(f"{field_name} is not a canonical digest")
        if _IDENTIFIER.fullmatch(self.target_login) is None:
            raise ValueError("workspace runtime target login is unsafe")
        home = Path(self.target_home)
        if (
            not home.is_absolute()
            or home == Path("/")
            or any(part in {"", ".", ".."} for part in home.parts[1:])
        ):
            raise ValueError("workspace runtime target home is unsafe")
        expected_destination = (
            f"{self.target_home}/.local/libexec/openzyme-workspace-runtime"
            if self.deployment_scope
            is WorkspaceRuntimeDeploymentScope.TARGET_PRINCIPAL_USER_LIBEXEC
            else WORKSPACE_RUNTIME_SYSTEM_DESTINATION
        )
        if self.destination_path != expected_destination:
            raise ValueError("workspace runtime destination path is not exact for its scope")
        if self.workspace_parent != (
            f"{self.target_home}/.local/state/openzyme-executor-workspaces"
        ):
            raise ValueError("workspace runtime workspace parent is not exact")
        if self.destination_state is WorkspaceRuntimeDestinationState.MISSING:
            if self.destination_pre_digest is not None:
                raise ValueError("missing destination cannot have a prior digest")
        elif self.destination_pre_digest is None or _DIGEST.fullmatch(
            self.destination_pre_digest
        ) is None:
            raise ValueError("present destination requires its exact prior digest")
        if self.live_effect_authorized:
            raise ValueError("deployment plan never authorizes its own effect")
        authority_fields = (
            self.installer_identity,
            self.privilege_mechanism,
            self.rollback_owner,
        )
        if self.status is WorkspaceRuntimeDeploymentStatus.READY:
            if any(value is None for value in authority_fields):
                raise ValueError("ready deployment requires exact installation authority")
        elif any(value is not None for value in authority_fields):
            raise ValueError("blocked deployment cannot contain partial authority")
        for value in authority_fields:
            if value is not None and _IDENTIFIER.fullmatch(value) is None:
                raise ValueError("deployment authority identity is unsafe")
        expected_owner = (
            self.target_login
            if self.deployment_scope
            is WorkspaceRuntimeDeploymentScope.TARGET_PRINCIPAL_USER_LIBEXEC
            else "root"
        )
        if (
            self.file_owner != expected_owner
            or self.file_mode != "0755"
            or _IDENTIFIER.fullmatch(self.file_group) is None
        ):
            raise ValueError("workspace runtime install owner and mode are exact")
        if self.plan_digest != "sha256:" + "0" * 64 and self.plan_digest != (
            canonical_sha256_digest(self.identity_payload)
        ):
            raise ValueError("workspace runtime deployment plan digest drifted")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "source_identity_digest": self.source_identity_digest,
            "target_subject_digest": self.target_subject_digest,
            "target_host_key_digest": self.target_host_key_digest,
            "helper_build_digest": self.helper_build_digest,
            "helper_version": self.helper_version,
            "target_login": self.target_login,
            "target_home": self.target_home,
            "deployment_scope": self.deployment_scope.value,
            "destination_path": self.destination_path,
            "workspace_parent": self.workspace_parent,
            "destination_state": self.destination_state.value,
            "destination_pre_digest": self.destination_pre_digest,
            "staging_path": self.staging_path,
            "backup_path": self.backup_path,
            "installer_identity": self.installer_identity,
            "privilege_mechanism": self.privilege_mechanism,
            "rollback_owner": self.rollback_owner,
            "file_owner": self.file_owner,
            "file_group": self.file_group,
            "file_mode": self.file_mode,
            "positive_probes": list(self.positive_probes),
            "negative_probes": list(self.negative_probes),
            "live_effect_authorized": self.live_effect_authorized,
            "status": self.status.value,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "plan_digest": self.plan_digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "WorkspaceRuntimeDeploymentPlan":
        expected = {
            "schema_version",
            "source_identity_digest",
            "target_subject_digest",
            "target_host_key_digest",
            "helper_build_digest",
            "helper_version",
            "target_login",
            "target_home",
            "deployment_scope",
            "destination_path",
            "workspace_parent",
            "destination_state",
            "destination_pre_digest",
            "staging_path",
            "backup_path",
            "installer_identity",
            "privilege_mechanism",
            "rollback_owner",
            "file_owner",
            "file_group",
            "file_mode",
            "positive_probes",
            "negative_probes",
            "live_effect_authorized",
            "status",
            "plan_digest",
        }
        if payload.get("schema_version") != cls.SCHEMA_VERSION or set(payload) != expected:
            raise ValueError("workspace runtime deployment plan fields are closed")
        return cls(
            source_identity_digest=str(payload["source_identity_digest"]),
            target_subject_digest=str(payload["target_subject_digest"]),
            target_host_key_digest=str(payload["target_host_key_digest"]),
            helper_build_digest=str(payload["helper_build_digest"]),
            helper_version=str(payload["helper_version"]),
            target_login=str(payload["target_login"]),
            target_home=str(payload["target_home"]),
            deployment_scope=WorkspaceRuntimeDeploymentScope(
                str(payload["deployment_scope"])
            ),
            destination_path=str(payload["destination_path"]),
            workspace_parent=str(payload["workspace_parent"]),
            destination_state=WorkspaceRuntimeDestinationState(
                str(payload["destination_state"])
            ),
            destination_pre_digest=(
                None
                if payload["destination_pre_digest"] is None
                else str(payload["destination_pre_digest"])
            ),
            staging_path=str(payload["staging_path"]),
            backup_path=str(payload["backup_path"]),
            installer_identity=(
                None
                if payload["installer_identity"] is None
                else str(payload["installer_identity"])
            ),
            privilege_mechanism=(
                None
                if payload["privilege_mechanism"] is None
                else str(payload["privilege_mechanism"])
            ),
            rollback_owner=(
                None
                if payload["rollback_owner"] is None
                else str(payload["rollback_owner"])
            ),
            file_owner=str(payload["file_owner"]),
            file_group=str(payload["file_group"]),
            file_mode=str(payload["file_mode"]),
            positive_probes=tuple(str(item) for item in payload["positive_probes"]),  # type: ignore[union-attr]
            negative_probes=tuple(str(item) for item in payload["negative_probes"]),  # type: ignore[union-attr]
            live_effect_authorized=bool(payload["live_effect_authorized"]),
            status=WorkspaceRuntimeDeploymentStatus(str(payload["status"])),
            plan_digest=str(payload["plan_digest"]),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeDeploymentAuthorization:
    authorization_id: str
    plan_digest: str
    operator_id: str
    installer_identity: str
    privilege_mechanism: str
    rollback_owner: str
    authorization_digest: str

    @classmethod
    def create(cls, **values: str) -> "WorkspaceRuntimeDeploymentAuthorization":
        payload = {
            "schema_version": WORKSPACE_RUNTIME_DEPLOYMENT_AUTHORIZATION_SCHEMA,
            **values,
        }
        return cls(**values, authorization_digest=canonical_sha256_digest(payload))

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.plan_digest) is None or _DIGEST.fullmatch(
            self.authorization_digest
        ) is None:
            raise ValueError("deployment authorization digest is invalid")
        for value in (
            self.authorization_id,
            self.operator_id,
            self.installer_identity,
            self.privilege_mechanism,
            self.rollback_owner,
        ):
            if _IDENTIFIER.fullmatch(value) is None:
                raise ValueError("deployment authorization identity is unsafe")
        if self.authorization_digest != canonical_sha256_digest(self.identity_payload):
            raise ValueError("deployment authorization digest drifted")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": WORKSPACE_RUNTIME_DEPLOYMENT_AUTHORIZATION_SCHEMA,
            "authorization_id": self.authorization_id,
            "plan_digest": self.plan_digest,
            "operator_id": self.operator_id,
            "installer_identity": self.installer_identity,
            "privilege_mechanism": self.privilege_mechanism,
            "rollback_owner": self.rollback_owner,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "authorization_digest": self.authorization_digest}

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "WorkspaceRuntimeDeploymentAuthorization":
        expected = {
            "schema_version",
            "authorization_id",
            "plan_digest",
            "operator_id",
            "installer_identity",
            "privilege_mechanism",
            "rollback_owner",
            "authorization_digest",
        }
        if (
            payload.get("schema_version")
            != WORKSPACE_RUNTIME_DEPLOYMENT_AUTHORIZATION_SCHEMA
            or set(payload) != expected
        ):
            raise ValueError("workspace runtime deployment authorization fields are closed")
        return cls(
            authorization_id=str(payload["authorization_id"]),
            plan_digest=str(payload["plan_digest"]),
            operator_id=str(payload["operator_id"]),
            installer_identity=str(payload["installer_identity"]),
            privilege_mechanism=str(payload["privilege_mechanism"]),
            rollback_owner=str(payload["rollback_owner"]),
            authorization_digest=str(payload["authorization_digest"]),
        )


def verify_workspace_runtime_deployment_authorization(
    plan: WorkspaceRuntimeDeploymentPlan,
    authorization: WorkspaceRuntimeDeploymentAuthorization | None,
    *,
    expected_operator_id: str,
) -> None:
    if plan.status is not WorkspaceRuntimeDeploymentStatus.READY:
        raise WorkspaceRuntimeDeploymentError(
            "blocked_deployment_authority",
            "deployment plan has no exact installation authority",
        )
    if authorization is None:
        raise WorkspaceRuntimeDeploymentError(
            "workspace_runtime_deployment_authorization_missing",
            "deployment requires a distinct one-shot authorization",
        )
    if (
        authorization.plan_digest != plan.plan_digest
        or authorization.operator_id != expected_operator_id
        or authorization.installer_identity != plan.installer_identity
        or authorization.privilege_mechanism != plan.privilege_mechanism
        or authorization.rollback_owner != plan.rollback_owner
    ):
        raise WorkspaceRuntimeDeploymentError(
            "workspace_runtime_deployment_authorization_drift",
            "deployment authorization differs from the exact plan",
        )


class WorkspaceRuntimeDeploymentError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeNativeQualification:
    helper_build_digest: str
    root_policy_digest: str
    principal_identity_digest: str
    positive_probes: tuple[str, ...]
    negative_probes: tuple[str, ...]
    all_passed: bool


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeDeploymentReceipt:
    plan_digest: str
    authorization_digest: str
    installed_digest: str
    destination_pre_digest: str | None
    native_qualification_digest: str
    rollback_performed: bool
    fallback_performed: bool
    receipt_digest: str

    @classmethod
    def create(cls, **values: object) -> "WorkspaceRuntimeDeploymentReceipt":
        payload = {
            "schema_version": WORKSPACE_RUNTIME_DEPLOYMENT_RECEIPT_SCHEMA,
            **values,
        }
        return cls(**values, receipt_digest=canonical_sha256_digest(payload))  # type: ignore[arg-type]

    def __post_init__(self) -> None:
        for value in (
            self.plan_digest,
            self.authorization_digest,
            self.installed_digest,
            self.native_qualification_digest,
            self.receipt_digest,
        ):
            if _DIGEST.fullmatch(value) is None:
                raise ValueError("workspace runtime deployment receipt digest is invalid")
        if self.destination_pre_digest is not None and _DIGEST.fullmatch(
            self.destination_pre_digest
        ) is None:
            raise ValueError("workspace runtime prior destination digest is invalid")
        if self.fallback_performed or self.rollback_performed:
            raise ValueError("successful deployment receipt cannot claim fallback or rollback")
        if self.receipt_digest != canonical_sha256_digest(self.identity_payload):
            raise ValueError("workspace runtime deployment receipt digest drifted")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": WORKSPACE_RUNTIME_DEPLOYMENT_RECEIPT_SCHEMA,
            "plan_digest": self.plan_digest,
            "authorization_digest": self.authorization_digest,
            "installed_digest": self.installed_digest,
            "destination_pre_digest": self.destination_pre_digest,
            "native_qualification_digest": self.native_qualification_digest,
            "rollback_performed": self.rollback_performed,
            "fallback_performed": self.fallback_performed,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "WorkspaceRuntimeDeploymentReceipt":
        expected = {
            "schema_version",
            "plan_digest",
            "authorization_digest",
            "installed_digest",
            "destination_pre_digest",
            "native_qualification_digest",
            "rollback_performed",
            "fallback_performed",
            "receipt_digest",
        }
        if (
            payload.get("schema_version") != WORKSPACE_RUNTIME_DEPLOYMENT_RECEIPT_SCHEMA
            or set(payload) != expected
        ):
            raise ValueError("workspace runtime deployment receipt fields are closed")
        return cls(
            plan_digest=str(payload["plan_digest"]),
            authorization_digest=str(payload["authorization_digest"]),
            installed_digest=str(payload["installed_digest"]),
            destination_pre_digest=(
                None
                if payload["destination_pre_digest"] is None
                else str(payload["destination_pre_digest"])
            ),
            native_qualification_digest=str(payload["native_qualification_digest"]),
            rollback_performed=bool(payload["rollback_performed"]),
            fallback_performed=bool(payload["fallback_performed"]),
            receipt_digest=str(payload["receipt_digest"]),
        )


class WorkspaceRuntimeDeploymentPort(Protocol):
    def observe_destination(self, path: str) -> tuple[str, str | None]: ...

    def stage(self, *, path: str, content: bytes) -> str: ...

    def install(self, plan: WorkspaceRuntimeDeploymentPlan) -> str: ...

    def qualify(
        self, plan: WorkspaceRuntimeDeploymentPlan
    ) -> WorkspaceRuntimeNativeQualification: ...

    def rollback(
        self,
        plan: WorkspaceRuntimeDeploymentPlan,
        *,
        installed_digest: str,
    ) -> str: ...


class WorkspaceRuntimeRemoteCommandPort(Protocol):
    def run_remote(self, script: str) -> tuple[int, str, str]: ...


@dataclass(slots=True)
class OpenSshWorkspaceRuntimeDeploymentPort:
    command_port: WorkspaceRuntimeRemoteCommandPort

    @staticmethod
    def _path(value: str) -> str:
        path = Path(value)
        if (
            not path.is_absolute()
            or path == Path("/")
            or any(part in {"", ".", ".."} for part in path.parts[1:])
        ):
            raise WorkspaceRuntimeDeploymentError(
                "workspace_runtime_deployment_path_invalid",
                "deployment path is not one protected absolute path",
            )
        return shlex.quote(value)

    def _run(self, script: str, *, phase: str) -> str:
        returncode, stdout, _stderr = self.command_port.run_remote(script)
        if returncode != 0:
            raise WorkspaceRuntimeDeploymentError(
                f"workspace_runtime_{phase}_failed",
                f"workspace runtime {phase} command failed",
            )
        return stdout.strip()

    def observe_destination(self, path: str) -> tuple[str, str | None]:
        destination = self._path(path)
        output = self._run(
            f"""set -eu
destination={destination}
if test -L "$destination"; then
  printf 'unsafe\n'
elif test -f "$destination"; then
  printf 'present\nsha256:'
  sha256sum "$destination" | cut -d' ' -f1
elif test -e "$destination"; then
  printf 'unsafe\n'
else
  printf 'missing\n'
fi
""",
            phase="destination_observation",
        ).splitlines()
        if output == ["missing"]:
            return "missing", None
        if (
            len(output) == 2
            and output[0] == "present"
            and _DIGEST.fullmatch(output[1]) is not None
        ):
            return "present", output[1]
        raise WorkspaceRuntimeDeploymentError(
            "workspace_runtime_destination_unsafe",
            "workspace runtime destination is a symlink or unsupported object",
        )

    def stage(self, *, path: str, content: bytes) -> str:
        staging = self._path(path)
        parent = self._path(str(Path(path).parent))
        encoded = shlex.quote(base64.b64encode(content).decode("ascii"))
        expected = "sha256:" + hashlib.sha256(content).hexdigest()
        expected_hex = shlex.quote(expected.removeprefix("sha256:"))
        output = self._run(
            f"""set -eu
parent={parent}
staging={staging}
expected={expected_hex}
if test -L "$parent" || test -e "$parent" && ! test -d "$parent"; then exit 64; fi
if ! test -d "$parent"; then install -d -m 0700 -- "$parent"; fi
test "$(stat -c '%u' "$parent")" = "$(id -u)"
chmod 0700 -- "$parent"
if test -L "$staging" || test -e "$staging" && ! test -f "$staging"; then exit 65; fi
if test -f "$staging"; then
  test "$(sha256sum "$staging" | cut -d' ' -f1)" = "$expected"
else
  temporary="$staging.tmp.$$"
  umask 077
  printf '%s' {encoded} | base64 -d > "$temporary"
  test "$(sha256sum "$temporary" | cut -d' ' -f1)" = "$expected"
  chmod 0700 -- "$temporary"
  mv -n -- "$temporary" "$staging"
  rm -f -- "$temporary"
fi
printf 'sha256:%s\n' "$(sha256sum "$staging" | cut -d' ' -f1)"
""",
            phase="staging",
        )
        if _DIGEST.fullmatch(output) is None:
            raise WorkspaceRuntimeDeploymentError(
                "workspace_runtime_staging_observation_invalid",
                "staging did not return one exact build digest",
            )
        return output

    def install(self, plan: WorkspaceRuntimeDeploymentPlan) -> str:
        destination = self._path(plan.destination_path)
        staging = self._path(plan.staging_path)
        backup = self._path(plan.backup_path)
        build_hex = shlex.quote(plan.helper_build_digest.removeprefix("sha256:"))
        pre_hex = (
            ""
            if plan.destination_pre_digest is None
            else plan.destination_pre_digest.removeprefix("sha256:")
        )
        output = self._run(
            f"""set -eu
destination={destination}
staging={staging}
backup={backup}
build={build_hex}
pre={shlex.quote(pre_hex)}
if test -f "$destination" && test "$(sha256sum "$destination" | cut -d' ' -f1)" = "$build"; then
  chmod 0755 -- "$destination"
  printf 'sha256:%s\n' "$build"
  exit 0
fi
test -f "$staging"
test "$(sha256sum "$staging" | cut -d' ' -f1)" = "$build"
if test -n "$pre"; then
  test -f "$destination" && ! test -L "$destination"
  test "$(sha256sum "$destination" | cut -d' ' -f1)" = "$pre"
  if test -e "$backup"; then
    test -f "$backup" && ! test -L "$backup"
    test "$(sha256sum "$backup" | cut -d' ' -f1)" = "$pre"
  else
    cp -p -- "$destination" "$backup"
    test "$(sha256sum "$backup" | cut -d' ' -f1)" = "$pre"
  fi
else
  test ! -e "$destination" && ! test -L "$destination"
fi
mv -- "$staging" "$destination"
chmod 0755 -- "$destination"
test "$(stat -c '%u' "$destination")" = "$(id -u)"
test "$(sha256sum "$destination" | cut -d' ' -f1)" = "$build"
printf 'sha256:%s\n' "$build"
""",
            phase="install",
        )
        if _DIGEST.fullmatch(output) is None:
            raise WorkspaceRuntimeDeploymentError(
                "workspace_runtime_install_observation_invalid",
                "install did not return one exact build digest",
            )
        return output

    def qualify(
        self, plan: WorkspaceRuntimeDeploymentPlan
    ) -> WorkspaceRuntimeNativeQualification:
        helper = self._path(plan.destination_path)
        parent = self._path(plan.workspace_parent)
        policy_id = "diannan-executor-workspace-v1"
        handle = "hpcws_" + plan.helper_build_digest.removeprefix("sha256:")[:32]
        symlink_handle = (
            "hpcws_" + plan.helper_build_digest.removeprefix("sha256:")[32:64]
        )
        owner_digest = plan.target_subject_digest
        output = self._run(
            f"""set -eu
helper={helper}
parent={parent}
handle={shlex.quote(handle)}
symlink_handle={shlex.quote(symlink_handle)}
owner={shlex.quote(owner_digest)}
policy_id={shlex.quote(policy_id)}
build={shlex.quote(plan.helper_build_digest)}
version_output=$("$helper" version)
test "$(printf '%s\n' "$version_output" | sed -n 's/^OPENZYME_WORKSPACE_RUNTIME_VERSION=//p')" = "1.0.0"
test "$(printf '%s\n' "$version_output" | sed -n 's/^OPENZYME_WORKSPACE_RUNTIME_BUILD_DIGEST=//p')" = "$build"
if test -L "$parent" || test -e "$parent" && ! test -d "$parent"; then exit 64; fi
if ! test -d "$parent"; then install -d -m 0700 -- "$parent"; fi
test "$(stat -c '%u' "$parent")" = "$(id -u)"
chmod 0700 -- "$parent"
policy_output=$("$helper" policy-digest --policy-id "$policy_id" --workspace-parent "$parent")
policy=$(printf '%s\n' "$policy_output" | sed -n 's/^OPENZYME_ROOT_POLICY_DIGEST=//p')
principal=$(printf '%s\n' "$policy_output" | sed -n 's/^OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST=//p')
case "$policy" in sha256:????????????????????????????????????????????????????????????????) ;; *) exit 65;; esac
case "$principal" in sha256:????????????????????????????????????????????????????????????????) ;; *) exit 66;; esac
root="$parent/$handle"
"$helper" provision --policy-id "$policy_id" --root-policy-digest "$policy" --workspace-root "$root" --owner-identity-digest "$owner" --runner-handle "$handle" >/dev/null
"$helper" verify --policy-id "$policy_id" --root-policy-digest "$policy" --workspace-root "$root" --owner-identity-digest "$owner" --runner-handle "$handle" >/dev/null
bad_owner=sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
if "$helper" verify --policy-id "$policy_id" --root-policy-digest "$policy" --workspace-root "$root" --owner-identity-digest "$bad_owner" --runner-handle "$handle" >/dev/null 2>&1; then exit 67; fi
other_parent="$parent-other"
if "$helper" verify --policy-id "$policy_id" --root-policy-digest "$policy" --workspace-root "$other_parent/$handle" --owner-identity-digest "$owner" --runner-handle "$handle" >/dev/null 2>&1; then exit 68; fi
symlink_root="$parent/$symlink_handle"
ln -s -- "$parent" "$symlink_root"
if "$helper" provision --policy-id "$policy_id" --root-policy-digest "$policy" --workspace-root "$symlink_root" --owner-identity-digest "$owner" --runner-handle "$symlink_handle" >/dev/null 2>&1; then exit 69; fi
rm -- "$symlink_root"
if "$helper" exec >/dev/null 2>&1; then exit 70; fi
settlement=sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
"$helper" cleanup --policy-id "$policy_id" --root-policy-digest "$policy" --workspace-root "$root" --owner-identity-digest "$owner" --runner-handle "$handle" --settlement-proof-digest "$settlement" >/dev/null
"$helper" cleanup --policy-id "$policy_id" --root-policy-digest "$policy" --workspace-root "$root" --owner-identity-digest "$owner" --runner-handle "$handle" --settlement-proof-digest "$settlement" >/dev/null
test ! -e "$root" && ! test -L "$root"
state="$parent/.openzyme-workspace-runtime-state/$handle.json"
test -f "$state" && ! test -L "$state"
rm -- "$state"
rmdir -- "$parent/.openzyme-workspace-runtime-state"
printf 'BUILD=%s\nPOLICY=%s\nPRINCIPAL=%s\n' "$build" "$policy" "$principal"
""",
            phase="native_qualification",
        )
        fields = dict(
            line.split("=", 1)
            for line in output.splitlines()
            if "=" in line
        )
        if (
            fields.get("BUILD") != plan.helper_build_digest
            or _DIGEST.fullmatch(fields.get("POLICY", "")) is None
            or _DIGEST.fullmatch(fields.get("PRINCIPAL", "")) is None
        ):
            raise WorkspaceRuntimeDeploymentError(
                "workspace_runtime_native_qualification_observation_invalid",
                "native qualification returned an incomplete identity closure",
            )
        return WorkspaceRuntimeNativeQualification(
            helper_build_digest=plan.helper_build_digest,
            root_policy_digest=fields["POLICY"],
            principal_identity_digest=fields["PRINCIPAL"],
            positive_probes=plan.positive_probes,
            negative_probes=plan.negative_probes,
            all_passed=True,
        )

    def rollback(
        self,
        plan: WorkspaceRuntimeDeploymentPlan,
        *,
        installed_digest: str,
    ) -> str:
        destination = self._path(plan.destination_path)
        backup = self._path(plan.backup_path)
        installed_hex = shlex.quote(installed_digest.removeprefix("sha256:"))
        pre_hex = (
            ""
            if plan.destination_pre_digest is None
            else plan.destination_pre_digest.removeprefix("sha256:")
        )
        output = self._run(
            f"""set -eu
destination={destination}
backup={backup}
installed={installed_hex}
pre={shlex.quote(pre_hex)}
test -f "$destination" && ! test -L "$destination"
test "$(sha256sum "$destination" | cut -d' ' -f1)" = "$installed"
if test -n "$pre"; then
  test -f "$backup" && ! test -L "$backup"
  test "$(sha256sum "$backup" | cut -d' ' -f1)" = "$pre"
  mv -- "$backup" "$destination"
  test "$(sha256sum "$destination" | cut -d' ' -f1)" = "$pre"
  printf 'sha256:%s\n' "$pre"
else
  rm -- "$destination"
  test ! -e "$destination" && ! test -L "$destination"
  printf 'sha256:%s\n' "$(printf missing | sha256sum | cut -d' ' -f1)"
fi
""",
            phase="rollback",
        )
        if _DIGEST.fullmatch(output) is None:
            raise WorkspaceRuntimeDeploymentError(
                "workspace_runtime_rollback_observation_invalid",
                "rollback did not return one exact terminal digest",
            )
        return output


@dataclass(slots=True)
class WorkspaceRuntimeDeploymentCoordinator:
    port: WorkspaceRuntimeDeploymentPort

    def execute(
        self,
        *,
        plan: WorkspaceRuntimeDeploymentPlan,
        authorization: WorkspaceRuntimeDeploymentAuthorization | None,
        expected_operator_id: str,
        helper_bytes: bytes,
    ) -> WorkspaceRuntimeDeploymentReceipt:
        verify_workspace_runtime_deployment_authorization(
            plan,
            authorization,
            expected_operator_id=expected_operator_id,
        )
        assert authorization is not None
        observed_state, observed_digest = self.port.observe_destination(
            plan.destination_path
        )
        if (
            observed_state != plan.destination_state.value
            or observed_digest != plan.destination_pre_digest
        ):
            raise WorkspaceRuntimeDeploymentError(
                "workspace_runtime_destination_prestate_drift",
                "destination changed after deployment plan creation",
            )
        content_digest = "sha256:" + hashlib.sha256(helper_bytes).hexdigest()
        if content_digest != plan.helper_build_digest:
            raise WorkspaceRuntimeDeploymentError(
                "workspace_runtime_deployment_bytes_drift",
                "helper bytes differ from the plan build digest",
            )
        if self.port.stage(path=plan.staging_path, content=helper_bytes) != content_digest:
            raise WorkspaceRuntimeDeploymentError(
                "workspace_runtime_staging_digest_drift",
                "target staging did not preserve exact helper bytes",
            )
        installed_digest = self.port.install(plan)
        if installed_digest != content_digest:
            self.port.rollback(plan, installed_digest=installed_digest)
            raise WorkspaceRuntimeDeploymentError(
                "workspace_runtime_install_digest_drift",
                "installed helper differs from the exact staged bytes",
            )
        qualification = self.port.qualify(plan)
        qualification_payload = {
            "helper_build_digest": qualification.helper_build_digest,
            "root_policy_digest": qualification.root_policy_digest,
            "principal_identity_digest": qualification.principal_identity_digest,
            "positive_probes": list(qualification.positive_probes),
            "negative_probes": list(qualification.negative_probes),
            "all_passed": qualification.all_passed,
        }
        qualification_digest = canonical_sha256_digest(qualification_payload)
        if (
            not qualification.all_passed
            or qualification.helper_build_digest != content_digest
            or qualification.positive_probes != plan.positive_probes
            or qualification.negative_probes != plan.negative_probes
        ):
            self.port.rollback(plan, installed_digest=installed_digest)
            raise WorkspaceRuntimeDeploymentError(
                "workspace_runtime_native_qualification_failed",
                "native helper qualification failed and exact rollback was requested",
            )
        return WorkspaceRuntimeDeploymentReceipt.create(
            plan_digest=plan.plan_digest,
            authorization_digest=authorization.authorization_digest,
            installed_digest=installed_digest,
            destination_pre_digest=plan.destination_pre_digest,
            native_qualification_digest=qualification_digest,
            rollback_performed=False,
            fallback_performed=False,
        )


def workspace_runtime_source_bytes() -> bytes:
    return Path(__file__).with_name("workspace_runtime.py").read_bytes()


__all__ = [
    "WORKSPACE_RUNTIME_SYSTEM_DESTINATION",
    "WorkspaceRuntimeDeploymentAuthorization",
    "WorkspaceRuntimeDeploymentCoordinator",
    "WorkspaceRuntimeDeploymentError",
    "WorkspaceRuntimeDeploymentPlan",
    "WorkspaceRuntimeDeploymentPort",
    "WorkspaceRuntimeRemoteCommandPort",
    "OpenSshWorkspaceRuntimeDeploymentPort",
    "WorkspaceRuntimeDeploymentReceipt",
    "WorkspaceRuntimeDeploymentStatus",
    "WorkspaceRuntimeDeploymentScope",
    "WorkspaceRuntimeDestinationState",
    "WorkspaceRuntimeNativeQualification",
    "verify_workspace_runtime_deployment_authorization",
    "workspace_runtime_source_bytes",
]
