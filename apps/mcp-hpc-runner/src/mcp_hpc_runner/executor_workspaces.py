from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
from typing import Any
from uuid import uuid4

from .config import RunnerConfig
from .transport import SshTransportManager


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_PROVISION_REQUEST_SCHEMA_VERSION = "executor_workspace_provision_request@1"
_PROVISION_RECEIPT_SCHEMA_VERSION = "executor_hpc_workspace_provision_receipt@1"
_CLEANUP_REQUEST_SCHEMA_VERSION = "executor_workspace_cleanup_request@1"
_CLEANUP_RECEIPT_SCHEMA_VERSION = "executor_hpc_workspace_cleanup_receipt@1"


class ExecutorWorkspaceProvisionError(RuntimeError):
    error_code = "executor_workspace_provision_failed"


class ExecutorWorkspaceProvisionInDoubt(ExecutorWorkspaceProvisionError):
    error_code = "executor_workspace_provision_dispatch_in_doubt"


@dataclass(frozen=True, slots=True)
class ExecutorWorkspaceProvisionRequest:
    intent_id: str
    intent_digest: str
    workspace_id: str
    remote_workspace_generation: int
    target_profile_digest: str
    repository_endpoint: str
    repository_remote_digest: str
    base_commit: str
    owner_identity_digest: str
    idempotency_key: str
    absolute_deadline: str
    schema_version: str = _PROVISION_REQUEST_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutorWorkspaceProvisionRequest":
        expected = {
            "schema_version",
            "intent_id",
            "intent_digest",
            "workspace_id",
            "remote_workspace_generation",
            "target_profile_digest",
            "repository_endpoint",
            "repository_remote_digest",
            "base_commit",
            "owner_identity_digest",
            "idempotency_key",
            "absolute_deadline",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("executor workspace provision request fields are closed")
        request = cls(
            **{
                key: value[key]
                for key in expected
                if key != "schema_version"
            }
        )
        if value["schema_version"] != _PROVISION_REQUEST_SCHEMA_VERSION:
            raise ValueError("executor workspace provision request schema is unsupported")
        return request

    def __post_init__(self) -> None:
        if (
            not isinstance(self.remote_workspace_generation, int)
            or isinstance(self.remote_workspace_generation, bool)
            or self.remote_workspace_generation < 1
        ):
            raise ValueError("remote_workspace_generation must be a positive integer")
        for name in (
            "intent_id",
            "intent_digest",
            "workspace_id",
            "target_profile_digest",
            "repository_endpoint",
            "repository_remote_digest",
            "base_commit",
            "owner_identity_digest",
            "idempotency_key",
            "absolute_deadline",
        ):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")
        for name in ("intent_id", "workspace_id", "idempotency_key"):
            if _IDENTIFIER.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} is not a safe identity")
        for name in (
            "intent_digest",
            "target_profile_digest",
            "repository_remote_digest",
            "owner_identity_digest",
        ):
            if _DIGEST.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} is not a sha256 digest")
        if not self.repository_endpoint.startswith("https://"):
            raise ValueError("executor workspace repository endpoint must use HTTPS")
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.base_commit) is None:
            raise ValueError(
                "executor workspace base commit must be an exact Git commit id"
            )
        if not self.absolute_deadline or any(
            character.isspace() for character in self.absolute_deadline
        ):
            raise ValueError("executor workspace absolute deadline is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "intent_id": self.intent_id,
            "intent_digest": self.intent_digest,
            "workspace_id": self.workspace_id,
            "remote_workspace_generation": self.remote_workspace_generation,
            "target_profile_digest": self.target_profile_digest,
            "repository_endpoint": self.repository_endpoint,
            "repository_remote_digest": self.repository_remote_digest,
            "base_commit": self.base_commit,
            "owner_identity_digest": self.owner_identity_digest,
            "idempotency_key": self.idempotency_key,
            "absolute_deadline": self.absolute_deadline,
        }


@dataclass(frozen=True, slots=True)
class ExecutorWorkspaceCleanupRequest:
    provision_request: ExecutorWorkspaceProvisionRequest
    cleanup_intent_id: str
    cleanup_intent_digest: str
    workspace_state_version: int
    settlement_proof_digest: str
    idempotency_key: str
    unsettled_effect_count: int
    schema_version: str = _CLEANUP_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != _CLEANUP_REQUEST_SCHEMA_VERSION:
            raise ValueError("executor workspace cleanup request schema is unsupported")
        if (
            not isinstance(self.workspace_state_version, int)
            or isinstance(self.workspace_state_version, bool)
            or self.workspace_state_version < 1
        ):
            raise ValueError("cleanup workspace state version must be positive")
        if (
            not isinstance(self.unsettled_effect_count, int)
            or isinstance(self.unsettled_effect_count, bool)
            or self.unsettled_effect_count != 0
        ):
            raise ValueError("cleanup requires zero unsettled effects")
        for name in (
            "cleanup_intent_id",
            "cleanup_intent_digest",
            "settlement_proof_digest",
            "idempotency_key",
        ):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")
        if _DIGEST.fullmatch(self.settlement_proof_digest) is None:
            raise ValueError("cleanup settlement proof digest is invalid")
        if _DIGEST.fullmatch(self.cleanup_intent_digest) is None:
            raise ValueError("cleanup intent digest is invalid")
        for name in ("cleanup_intent_id", "idempotency_key"):
            if _IDENTIFIER.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} is not a safe identity")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutorWorkspaceCleanupRequest":
        expected = {
            "schema_version",
            "provision_request",
            "cleanup_intent_id",
            "cleanup_intent_digest",
            "workspace_state_version",
            "settlement_proof_digest",
            "idempotency_key",
            "unsettled_effect_count",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("executor workspace cleanup request fields are closed")
        if value["schema_version"] != _CLEANUP_REQUEST_SCHEMA_VERSION:
            raise ValueError("executor workspace cleanup request schema is unsupported")
        provision_request = value["provision_request"]
        if not isinstance(provision_request, dict):
            raise ValueError("cleanup provision_request must be an object")
        return cls(
            provision_request=ExecutorWorkspaceProvisionRequest.from_dict(
                provision_request
            ),
            cleanup_intent_id=value["cleanup_intent_id"],
            cleanup_intent_digest=value["cleanup_intent_digest"],
            workspace_state_version=value["workspace_state_version"],
            settlement_proof_digest=value["settlement_proof_digest"],
            idempotency_key=value["idempotency_key"],
            unsettled_effect_count=value["unsettled_effect_count"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provision_request": self.provision_request.to_dict(),
            "cleanup_intent_id": self.cleanup_intent_id,
            "cleanup_intent_digest": self.cleanup_intent_digest,
            "workspace_state_version": self.workspace_state_version,
            "settlement_proof_digest": self.settlement_proof_digest,
            "idempotency_key": self.idempotency_key,
            "unsettled_effect_count": self.unsettled_effect_count,
        }


class ExecutorWorkspaceProvisioningService:
    def __init__(
        self,
        config: RunnerConfig,
        transport: SshTransportManager,
    ) -> None:
        self.config = config
        self.transport = transport
        self._lock = threading.RLock()
        self._state_root = config.control_root / "executor-workspaces"

    def provision(
        self,
        request: ExecutorWorkspaceProvisionRequest,
    ) -> dict[str, str]:
        self._require_activated_target(request, require_unexpired=True)
        with self._lock:
            binding = self._load_or_create_binding(request)
            receipt = self._read_receipt(binding)
            if receipt is not None:
                return receipt
            remote_result = self._provision_remote(request, binding)
            if remote_result.returncode != 0:
                if remote_result.timed_out or remote_result.process_started:
                    raise ExecutorWorkspaceProvisionInDoubt(
                        "remote provisioning may have accepted the exact intent"
                    )
                raise ExecutorWorkspaceProvisionError(
                    "remote provisioning did not start"
                )
            observed = self._parse_remote_receipt(remote_result.stdout)
            receipt = self._build_receipt(request, binding, observed)
            self._write_receipt_once(binding, receipt)
            return receipt

    def inspect(
        self,
        request: ExecutorWorkspaceProvisionRequest,
    ) -> dict[str, str] | None:
        self._require_activated_target(request)
        with self._lock:
            binding = self._load_binding(request)
            if binding is None:
                return None
            receipt = self._read_receipt(binding)
            if receipt is not None:
                return receipt
            result = self.transport.run_ssh(
                [
                    "/bin/bash",
                    "-euo",
                    "pipefail",
                    "-c",
                    self._inspect_script(),
                    "openzyme-executor-workspace-inspect",
                    str(binding["remote_sidecar_path"]),
                ],
                timeout=self.config.execution.preflight_timeout_seconds,
                stage="executor_workspace_reconcile",
            )
            if result.returncode != 0:
                return None
            observed = self._parse_remote_receipt(result.stdout)
            receipt = self._build_receipt(request, binding, observed)
            self._write_receipt_once(binding, receipt)
            return receipt

    def cleanup(self, request: ExecutorWorkspaceCleanupRequest) -> dict[str, Any]:
        provision = request.provision_request
        self._require_activated_target(provision)
        with self._lock:
            binding = self._load_binding(provision)
            if binding is None:
                raise ExecutorWorkspaceProvisionError(
                    "cleanup requires the exact persisted runner binding"
                )
            provision_receipt = self._read_receipt(binding)
            if provision_receipt is None:
                raise ExecutorWorkspaceProvisionError(
                    "cleanup requires the exact provision receipt"
                )
            existing = self._read_cleanup_receipt(binding, request)
            if existing is not None:
                return existing
            result = self.transport.run_ssh(
                [
                    "/bin/bash",
                    "-euo",
                    "pipefail",
                    "-c",
                    self._cleanup_script(),
                    "openzyme-executor-workspace-cleanup",
                    self.config.executor_workspace.workspace_root,
                    binding["remote_workspace_path"],
                    binding["remote_sidecar_path"],
                    self._remote_cleanup_path(binding),
                    binding["runner_handle"],
                    provision.intent_digest,
                    provision_receipt["remote_root_digest"],
                    request.cleanup_intent_id,
                    request.cleanup_intent_digest,
                    request.settlement_proof_digest,
                    str(self.config.executor_workspace.isolation_command),
                    self.config.executor_workspace.os_principal_policy_id,
                    str(self.config.executor_workspace.root_policy_digest),
                    provision.owner_identity_digest,
                ],
                timeout=self.config.execution.staging_timeout_seconds,
                stage="executor_workspace_cleanup",
            )
            if result.returncode != 0:
                if result.timed_out or result.process_started:
                    raise ExecutorWorkspaceProvisionInDoubt(
                        "remote cleanup may have affected the exact workspace"
                    )
                raise ExecutorWorkspaceProvisionError("remote cleanup did not start")
            observed = self._parse_remote_cleanup_receipt(result.stdout)
            receipt = self._build_cleanup_receipt(
                request,
                binding,
                provision_receipt,
                observed,
            )
            self._write_cleanup_receipt_once(binding, request, receipt)
            return receipt

    def inspect_cleanup(
        self,
        request: ExecutorWorkspaceCleanupRequest,
    ) -> dict[str, Any] | None:
        provision = request.provision_request
        self._require_activated_target(provision)
        with self._lock:
            binding = self._load_binding(provision)
            if binding is None:
                return None
            provision_receipt = self._read_receipt(binding)
            if provision_receipt is None:
                return None
            existing = self._read_cleanup_receipt(binding, request)
            if existing is not None:
                return existing
            result = self.transport.run_ssh(
                [
                    "/bin/bash",
                    "-euo",
                    "pipefail",
                    "-c",
                    self._inspect_script(),
                    "openzyme-executor-workspace-cleanup-inspect",
                    self._remote_cleanup_path(binding),
                ],
                timeout=self.config.execution.preflight_timeout_seconds,
                stage="executor_workspace_cleanup_reconcile",
            )
            if result.returncode != 0:
                return None
            observed = self._parse_remote_cleanup_receipt(result.stdout)
            receipt = self._build_cleanup_receipt(
                request,
                binding,
                provision_receipt,
                observed,
            )
            self._write_cleanup_receipt_once(binding, request, receipt)
            return receipt

    def verify(self, request: ExecutorWorkspaceProvisionRequest) -> dict[str, Any]:
        self._require_activated_target(request)
        with self._lock:
            binding = self._load_binding(request)
            if binding is None:
                raise ExecutorWorkspaceProvisionError(
                    "workspace verification requires exact runner binding"
                )
            receipt = self._read_receipt(binding)
            if receipt is None:
                raise ExecutorWorkspaceProvisionError(
                    "workspace verification requires exact provision receipt"
                )
            result = self.transport.run_ssh(
                [
                    "/bin/bash",
                    "-euo",
                    "pipefail",
                    "-c",
                    self._verify_script(),
                    "openzyme-executor-workspace-verify",
                    binding["remote_sidecar_path"],
                    binding["remote_workspace_path"],
                    binding["runner_handle"],
                    request.intent_digest,
                    request.repository_endpoint,
                    request.base_commit,
                    request.owner_identity_digest,
                    str(self.config.executor_workspace.isolation_command),
                    self.config.executor_workspace.os_principal_policy_id,
                    str(self.config.executor_workspace.root_policy_digest),
                ],
                timeout=self.config.execution.preflight_timeout_seconds,
                stage="executor_workspace_verify",
            )
            if result.returncode != 0:
                raise ExecutorWorkspaceProvisionError(
                    "workspace verification transport failed"
                )
            facts = self._parse_remote_verification(result.stdout)
            payload: dict[str, Any] = {
                "schema_version": "executor_hpc_workspace_observation@1",
                "workspace_id": request.workspace_id,
                "intent_digest": request.intent_digest,
                "runner_handle": binding["runner_handle"],
                "remote_root_digest": receipt["remote_root_digest"],
                "kind": facts["OPENZYME_VERIFY_KIND"],
                "repository_remote_digest": (
                    request.repository_remote_digest
                    if facts["OPENZYME_VERIFY_REMOTE_MATCH"] == "1"
                    else None
                ),
                "head_commit": facts["OPENZYME_VERIFY_HEAD"] or None,
                "independent_git_directory": (
                    facts["OPENZYME_VERIFY_INDEPENDENT_GIT"] == "1"
                ),
                "protected_root_mode": (
                    facts["OPENZYME_VERIFY_ROOT_MODE"] or None
                ),
                "os_principal_identity_digest": (
                    facts["OPENZYME_VERIFY_OS_PRINCIPAL_IDENTITY_DIGEST"]
                    or None
                ),
                "isolation_receipt_digest": (
                    facts["OPENZYME_VERIFY_ISOLATION_RECEIPT_DIGEST"] or None
                ),
                "observed_at": facts["OPENZYME_VERIFY_OBSERVED_AT"],
            }
            return {**payload, "observation_digest": self._digest(payload)}

    def _require_activated_target(
        self,
        request: ExecutorWorkspaceProvisionRequest,
        *,
        require_unexpired: bool = False,
    ) -> None:
        target = self.config.executor_workspace
        if not target.activated:
            raise ExecutorWorkspaceProvisionError(
                "executor workspace mode is not activated for this target"
            )
        if request.target_profile_digest != target.target_profile_digest:
            raise ExecutorWorkspaceProvisionError(
                "executor workspace target profile identity drifted"
            )
        if not self.transport.enabled:
            raise ExecutorWorkspaceProvisionError(
                "runner-private SSH transport is unavailable"
            )
        try:
            deadline = datetime.fromisoformat(request.absolute_deadline)
        except ValueError as exc:
            raise ExecutorWorkspaceProvisionError(
                "executor workspace absolute deadline is invalid"
            ) from exc
        if deadline.tzinfo is None or (
            require_unexpired and deadline <= datetime.now(tz=UTC)
        ):
            raise ExecutorWorkspaceProvisionError(
                "executor workspace absolute deadline expired before remote action"
            )

    def _load_or_create_binding(
        self,
        request: ExecutorWorkspaceProvisionRequest,
    ) -> dict[str, Any]:
        existing = self._load_binding(request)
        if existing is not None:
            self._write_workspace_index_once(request, existing)
            return existing
        self._prepare_state_root()
        handle = f"hpcws_{uuid4().hex}"
        target = self.config.executor_workspace
        workspace_path = str(PurePosixPath(target.workspace_root) / handle)
        sidecar_path = str(
            PurePosixPath(target.sidecar_root)
            / f"{request.intent_digest.removeprefix('sha256:')}.receipt"
        )
        binding = {
            "schema_version": "executor_workspace_runner_binding@1",
            "intent_digest": request.intent_digest,
            "request_digest": self._digest(request.to_dict()),
            "workspace_id": request.workspace_id,
            "remote_workspace_generation": request.remote_workspace_generation,
            "target_profile_digest": request.target_profile_digest,
            "runner_handle": handle,
            "remote_workspace_path": workspace_path,
            "remote_sidecar_path": sidecar_path,
        }
        path = self._binding_path(request.intent_digest)
        try:
            self._write_json_once(path, binding)
        except FileExistsError:
            existing = self._load_binding(request)
            if existing is None:
                raise ExecutorWorkspaceProvisionError(
                    "executor workspace runner binding disappeared"
                )
            binding = existing
        self._write_workspace_index_once(request, binding)
        return binding

    def resolve_private_workspace(
        self,
        *,
        workspace_id: str,
        remote_workspace_generation: int,
        target_profile_digest: str,
    ) -> dict[str, Any]:
        path = self._workspace_index_path(
            workspace_id,
            remote_workspace_generation,
        )
        try:
            index = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExecutorWorkspaceProvisionError(
                "executor workspace private index is unavailable"
            ) from exc
        expected = {
            "schema_version",
            "workspace_id",
            "remote_workspace_generation",
            "target_profile_digest",
            "intent_digest",
            "binding_digest",
        }
        if (
            not isinstance(index, dict)
            or set(index) != expected
            or index["schema_version"] != "executor_workspace_runner_index@1"
            or index["workspace_id"] != workspace_id
            or index["remote_workspace_generation"]
            != remote_workspace_generation
            or index["target_profile_digest"] != target_profile_digest
        ):
            raise ExecutorWorkspaceProvisionError(
                "executor workspace private index identity drifted"
            )
        binding_path = self._binding_path(str(index["intent_digest"]))
        try:
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExecutorWorkspaceProvisionError(
                "executor workspace private binding is unavailable"
            ) from exc
        if (
            not isinstance(binding, dict)
            or self._digest(binding) != index["binding_digest"]
            or binding.get("workspace_id") != workspace_id
            or binding.get("remote_workspace_generation")
            != remote_workspace_generation
            or binding.get("target_profile_digest") != target_profile_digest
        ):
            raise ExecutorWorkspaceProvisionError(
                "executor workspace private binding crossed its index"
            )
        return binding

    def _write_workspace_index_once(
        self,
        request: ExecutorWorkspaceProvisionRequest,
        binding: dict[str, Any],
    ) -> None:
        index = {
            "schema_version": "executor_workspace_runner_index@1",
            "workspace_id": request.workspace_id,
            "remote_workspace_generation": request.remote_workspace_generation,
            "target_profile_digest": request.target_profile_digest,
            "intent_digest": request.intent_digest,
            "binding_digest": self._digest(binding),
        }
        path = self._workspace_index_path(
            request.workspace_id,
            request.remote_workspace_generation,
        )
        try:
            self._write_json_once(path, index)
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ExecutorWorkspaceProvisionError(
                    "executor workspace private index is unreadable"
                ) from exc
            if existing != index:
                raise ExecutorWorkspaceProvisionError(
                    "executor workspace private index conflicts"
                )

    def _load_binding(
        self,
        request: ExecutorWorkspaceProvisionRequest,
    ) -> dict[str, Any] | None:
        path = self._binding_path(request.intent_digest)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (
            raw.get("schema_version") != "executor_workspace_runner_binding@1"
            or raw.get("intent_digest") != request.intent_digest
            or raw.get("request_digest") != self._digest(request.to_dict())
            or raw.get("workspace_id") != request.workspace_id
            or raw.get("remote_workspace_generation")
            != request.remote_workspace_generation
            or raw.get("target_profile_digest") != request.target_profile_digest
            or _IDENTIFIER.fullmatch(str(raw.get("runner_handle") or "")) is None
        ):
            raise ExecutorWorkspaceProvisionError(
                "executor workspace runner binding identity drifted"
            )
        return dict(raw)

    def _provision_remote(
        self,
        request: ExecutorWorkspaceProvisionRequest,
        binding: dict[str, str],
    ) -> Any:
        target = self.config.executor_workspace
        return self.transport.run_ssh(
            [
                "/bin/bash",
                "-euo",
                "pipefail",
                "-c",
                self._provision_script(),
                "openzyme-executor-workspace-provision",
                target.sidecar_root,
                binding["remote_sidecar_path"],
                binding["remote_workspace_path"],
                binding["runner_handle"],
                request.intent_digest,
                request.repository_endpoint,
                request.base_commit,
                request.owner_identity_digest,
                str(target.isolation_command),
                target.os_principal_policy_id,
                str(target.root_policy_digest),
            ],
            timeout=self.config.execution.staging_timeout_seconds,
            stage="executor_workspace_provision",
        )

    @staticmethod
    def _provision_script() -> str:
        return r"""
sidecar_root="$1"
receipt_path="$2"
workspace_path="$3"
runner_handle="$4"
intent_digest="$5"
repository_endpoint="$6"
base_commit="$7"
owner_identity_digest="$8"
isolation_command="$9"
os_principal_policy_id="${10}"
root_policy_digest="${11}"
created_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
umask 077
install -d -m 0700 -- "${sidecar_root}"
if [[ -f "${receipt_path}" ]]; then
  cat -- "${receipt_path}"
  exit 0
fi
lock_dir="${receipt_path}.lock"
if ! mkdir -m 0700 -- "${lock_dir}"; then
  if [[ -f "${receipt_path}" ]]; then
    cat -- "${receipt_path}"
    exit 0
  fi
  exit 75
fi
trap 'rmdir -- "${lock_dir}"' EXIT
if [[ -f "${receipt_path}" ]]; then
  cat -- "${receipt_path}"
  exit 0
fi
if [[ -e "${workspace_path}" ]]; then
  test -d "${workspace_path}"
  isolation_operation=verify
else
  isolation_operation=provision
fi
isolation_output="$(
  "${isolation_command}" "${isolation_operation}" \
      --policy-id "${os_principal_policy_id}" \
      --root-policy-digest "${root_policy_digest}" \
      --workspace-root "${workspace_path}" \
      --owner-identity-digest "${owner_identity_digest}" \
      --runner-handle "${runner_handle}"
)"
os_principal_identity_digest="$(
  printf '%s\n' "${isolation_output}" \
    | sed -n 's/^OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST=//p'
)"
isolation_receipt_digest="$(
  printf '%s\n' "${isolation_output}" \
    | sed -n 's/^OPENZYME_ISOLATION_RECEIPT_DIGEST=//p'
)"
[[ "${os_principal_identity_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "${isolation_receipt_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
test -d "${workspace_path}"
test "$(stat -c '%a' -- "${workspace_path}")" = "700"
recovered_existing_repo=0
if [[ ! -e "${workspace_path}/repo" ]]; then
  git clone --no-checkout -- "${repository_endpoint}" "${workspace_path}/repo"
elif [[ ! -d "${workspace_path}/repo/.git" ]] \
  || [[ -f "${workspace_path}/repo/.git" ]] \
  || [[ -e "${workspace_path}/repo/.git/objects/info/alternates" ]] \
  || [[ "$(git -C "${workspace_path}/repo" remote get-url origin)" != "${repository_endpoint}" ]]; then
  exit 73
else
  recovered_existing_repo=1
fi
if [[ "${recovered_existing_repo}" = "1" ]]; then
  git -C "${workspace_path}/repo" fetch --no-tags -- origin "${base_commit}"
fi
git -C "${workspace_path}/repo" checkout --detach "${base_commit}"
git -C "${workspace_path}/repo" lfs install --local
git -C "${workspace_path}/repo" lfs pull
test "$(git -C "${workspace_path}/repo" rev-parse HEAD)" = "${base_commit}"
test "$(git -C "${workspace_path}/repo" remote get-url origin)" = "${repository_endpoint}"
install -d -m 0700 -- "${workspace_path}/scratch" "${workspace_path}/runs"
temporary="${receipt_path}.tmp.$$"
{
  printf 'OPENZYME_RUNNER_HANDLE=%s\n' "${runner_handle}"
  printf 'OPENZYME_INTENT_DIGEST=%s\n' "${intent_digest}"
  printf 'OPENZYME_WORKSPACE_PATH=%s\n' "${workspace_path}"
  printf 'OPENZYME_BASE_COMMIT=%s\n' "${base_commit}"
  printf 'OPENZYME_OWNER_DIGEST=%s\n' "${owner_identity_digest}"
  printf 'OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST=%s\n' "${os_principal_identity_digest}"
  printf 'OPENZYME_ISOLATION_RECEIPT_DIGEST=%s\n' "${isolation_receipt_digest}"
  printf 'OPENZYME_CREATED_AT=%s\n' "${created_at}"
} >"${temporary}"
chmod 0600 "${temporary}"
mv -n -- "${temporary}" "${receipt_path}"
rm -f -- "${temporary}"
cat -- "${receipt_path}"
""".strip()

    @staticmethod
    def _inspect_script() -> str:
        return r"""
receipt_path="$1"
test -f "${receipt_path}"
cat -- "${receipt_path}"
""".strip()

    @staticmethod
    def _cleanup_script() -> str:
        return r"""
workspace_root="$1"
workspace_path="$2"
provision_receipt_path="$3"
cleanup_receipt_path="$4"
runner_handle="$5"
intent_digest="$6"
remote_root_digest="$7"
cleanup_intent_id="$8"
cleanup_intent_digest="$9"
settlement_proof_digest="${10}"
isolation_command="${11}"
os_principal_policy_id="${12}"
root_policy_digest="${13}"
owner_identity_digest="${14}"
created_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
umask 077
case "${workspace_path}" in
  "${workspace_root}"/hpcws_*) ;;
  *) exit 64 ;;
esac
test -f "${provision_receipt_path}"
grep -Fqx -- "OPENZYME_RUNNER_HANDLE=${runner_handle}" "${provision_receipt_path}"
grep -Fqx -- "OPENZYME_INTENT_DIGEST=${intent_digest}" "${provision_receipt_path}"
grep -Fqx -- "OPENZYME_WORKSPACE_PATH=${workspace_path}" "${provision_receipt_path}"
if [[ -f "${cleanup_receipt_path}" ]]; then
  cat -- "${cleanup_receipt_path}"
  exit 0
fi
lock_dir="${cleanup_receipt_path}.lock"
if ! mkdir -m 0700 -- "${lock_dir}"; then
  if [[ -f "${cleanup_receipt_path}" ]]; then
    cat -- "${cleanup_receipt_path}"
    exit 0
  fi
  exit 75
fi
trap 'rmdir -- "${lock_dir}"' EXIT
if [[ -f "${cleanup_receipt_path}" ]]; then
  cat -- "${cleanup_receipt_path}"
  exit 0
fi
cleanup_output="$(
  "${isolation_command}" cleanup \
    --policy-id "${os_principal_policy_id}" \
    --root-policy-digest "${root_policy_digest}" \
    --workspace-root "${workspace_path}" \
    --owner-identity-digest "${owner_identity_digest}" \
    --runner-handle "${runner_handle}" \
    --settlement-proof-digest "${settlement_proof_digest}"
)"
cleanup_disposition="$(
  printf '%s\n' "${cleanup_output}" \
    | sed -n 's/^OPENZYME_CLEANUP_DISPOSITION=//p'
)"
isolation_cleanup_receipt_digest="$(
  printf '%s\n' "${cleanup_output}" \
    | sed -n 's/^OPENZYME_ISOLATION_CLEANUP_RECEIPT_DIGEST=//p'
)"
test "${cleanup_disposition}" = "deleted"
[[ "${isolation_cleanup_receipt_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
test ! -e "${workspace_path}"
temporary="${cleanup_receipt_path}.tmp.$$"
{
  printf 'OPENZYME_CLEANUP_RUNNER_HANDLE=%s\n' "${runner_handle}"
  printf 'OPENZYME_PROVISION_INTENT_DIGEST=%s\n' "${intent_digest}"
  printf 'OPENZYME_CLEANUP_ROOT_DIGEST=%s\n' "${remote_root_digest}"
  printf 'OPENZYME_CLEANUP_INTENT_ID=%s\n' "${cleanup_intent_id}"
  printf 'OPENZYME_CLEANUP_INTENT_DIGEST=%s\n' "${cleanup_intent_digest}"
  printf 'OPENZYME_SETTLEMENT_PROOF_DIGEST=%s\n' "${settlement_proof_digest}"
  printf 'OPENZYME_ISOLATION_CLEANUP_RECEIPT_DIGEST=%s\n' "${isolation_cleanup_receipt_digest}"
  printf 'OPENZYME_CLEANUP_DISPOSITION=deleted\n'
  printf 'OPENZYME_CLEANUP_CREATED_AT=%s\n' "${created_at}"
} >"${temporary}"
chmod 0600 "${temporary}"
mv -n -- "${temporary}" "${cleanup_receipt_path}"
rm -f -- "${temporary}"
cat -- "${cleanup_receipt_path}"
""".strip()

    @staticmethod
    def _verify_script() -> str:
        return r"""
receipt_path="$1"
workspace_path="$2"
runner_handle="$3"
intent_digest="$4"
repository_endpoint="$5"
base_commit="$6"
owner_identity_digest="$7"
isolation_command="$8"
os_principal_policy_id="$9"
root_policy_digest="${10}"
observed_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
kind=matches
remote_match=0
independent_git=0
root_mode=""
head=""
isolation_verified=0
isolation_output="$(
  "${isolation_command}" verify \
    --policy-id "${os_principal_policy_id}" \
    --root-policy-digest "${root_policy_digest}" \
    --workspace-root "${workspace_path}" \
    --owner-identity-digest "${owner_identity_digest}" \
    --runner-handle "${runner_handle}" 2>/dev/null || true
)"
os_principal_identity_digest="$(
  printf '%s\n' "${isolation_output}" \
    | sed -n 's/^OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST=//p'
)"
isolation_receipt_digest="$(
  printf '%s\n' "${isolation_output}" \
    | sed -n 's/^OPENZYME_ISOLATION_RECEIPT_DIGEST=//p'
)"
if [[ "${os_principal_identity_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] \
  && [[ "${isolation_receipt_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  isolation_verified=1
fi
if [[ ! -d "${workspace_path}" ]]; then
  kind=missing
elif [[ ! -f "${receipt_path}" ]]; then
  kind=invalid
else
  root_mode="$(stat -c '%a' -- "${workspace_path}" 2>/dev/null || true)"
  if [[ "${root_mode}" != "700" ]] \
    || ! grep -Fqx -- "OPENZYME_RUNNER_HANDLE=${runner_handle}" "${receipt_path}" \
    || ! grep -Fqx -- "OPENZYME_INTENT_DIGEST=${intent_digest}" "${receipt_path}" \
    || ! grep -Fqx -- "OPENZYME_WORKSPACE_PATH=${workspace_path}" "${receipt_path}" \
    || ! grep -Fqx -- "OPENZYME_BASE_COMMIT=${base_commit}" "${receipt_path}" \
    || ! grep -Fqx -- "OPENZYME_OWNER_DIGEST=${owner_identity_digest}" "${receipt_path}" \
    || ! grep -Fqx -- "OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST=${os_principal_identity_digest}" "${receipt_path}" \
    || ! grep -Fqx -- "OPENZYME_ISOLATION_RECEIPT_DIGEST=${isolation_receipt_digest}" "${receipt_path}" \
    || [[ "${isolation_verified}" != "1" ]] \
    || [[ ! -d "${workspace_path}/repo/.git" ]] \
    || [[ -f "${workspace_path}/repo/.git" ]] \
    || [[ -e "${workspace_path}/repo/.git/objects/info/alternates" ]]; then
    kind=invalid
  else
    observed_remote="$(git -C "${workspace_path}/repo" remote get-url origin 2>/dev/null || true)"
    head="$(git -C "${workspace_path}/repo" rev-parse --verify HEAD 2>/dev/null || true)"
    if [[ "${observed_remote}" = "${repository_endpoint}" ]]; then
      remote_match=1
    fi
    if [[ "${remote_match}" = "1" ]] \
      && [[ -n "${head}" ]] \
      && git -C "${workspace_path}/repo" lfs env >/dev/null 2>&1; then
      independent_git=1
    else
      kind=invalid
    fi
  fi
fi
printf 'OPENZYME_VERIFY_KIND=%s\n' "${kind}"
printf 'OPENZYME_VERIFY_REMOTE_MATCH=%s\n' "${remote_match}"
printf 'OPENZYME_VERIFY_INDEPENDENT_GIT=%s\n' "${independent_git}"
printf 'OPENZYME_VERIFY_ROOT_MODE=%s\n' "${root_mode}"
printf 'OPENZYME_VERIFY_HEAD=%s\n' "${head}"
printf 'OPENZYME_VERIFY_OS_PRINCIPAL_IDENTITY_DIGEST=%s\n' "${os_principal_identity_digest}"
printf 'OPENZYME_VERIFY_ISOLATION_RECEIPT_DIGEST=%s\n' "${isolation_receipt_digest}"
printf 'OPENZYME_VERIFY_OBSERVED_AT=%s\n' "${observed_at}"
""".strip()

    @staticmethod
    def _parse_remote_receipt(stdout: str) -> dict[str, str]:
        allowed = {
            "OPENZYME_RUNNER_HANDLE",
            "OPENZYME_INTENT_DIGEST",
            "OPENZYME_WORKSPACE_PATH",
            "OPENZYME_BASE_COMMIT",
            "OPENZYME_OWNER_DIGEST",
            "OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST",
            "OPENZYME_ISOLATION_RECEIPT_DIGEST",
            "OPENZYME_CREATED_AT",
        }
        parsed: dict[str, str] = {}
        for line in stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in allowed:
                parsed[key] = value
        if set(parsed) != allowed:
            raise ExecutorWorkspaceProvisionError(
                "remote workspace receipt fields are incomplete"
            )
        return parsed

    @staticmethod
    def _parse_remote_cleanup_receipt(stdout: str) -> dict[str, str]:
        allowed = {
            "OPENZYME_CLEANUP_RUNNER_HANDLE",
            "OPENZYME_PROVISION_INTENT_DIGEST",
            "OPENZYME_CLEANUP_INTENT_DIGEST",
            "OPENZYME_CLEANUP_INTENT_ID",
            "OPENZYME_CLEANUP_ROOT_DIGEST",
            "OPENZYME_CLEANUP_DISPOSITION",
            "OPENZYME_SETTLEMENT_PROOF_DIGEST",
            "OPENZYME_ISOLATION_CLEANUP_RECEIPT_DIGEST",
            "OPENZYME_CLEANUP_CREATED_AT",
        }
        parsed: dict[str, str] = {}
        for line in stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in allowed:
                parsed[key] = value
        if set(parsed) != allowed:
            raise ExecutorWorkspaceProvisionError(
                "remote cleanup receipt fields are incomplete"
            )
        return parsed

    @staticmethod
    def _parse_remote_verification(stdout: str) -> dict[str, str]:
        allowed = {
            "OPENZYME_VERIFY_KIND",
            "OPENZYME_VERIFY_REMOTE_MATCH",
            "OPENZYME_VERIFY_INDEPENDENT_GIT",
            "OPENZYME_VERIFY_ROOT_MODE",
            "OPENZYME_VERIFY_HEAD",
            "OPENZYME_VERIFY_OS_PRINCIPAL_IDENTITY_DIGEST",
            "OPENZYME_VERIFY_ISOLATION_RECEIPT_DIGEST",
            "OPENZYME_VERIFY_OBSERVED_AT",
        }
        parsed: dict[str, str] = {}
        for line in stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in allowed:
                parsed[key] = value
        if (
            set(parsed) != allowed
            or parsed["OPENZYME_VERIFY_KIND"]
            not in {"matches", "missing", "invalid"}
            or parsed["OPENZYME_VERIFY_REMOTE_MATCH"] not in {"0", "1"}
            or parsed["OPENZYME_VERIFY_INDEPENDENT_GIT"] not in {"0", "1"}
        ):
            raise ExecutorWorkspaceProvisionError(
                "remote workspace verification facts are invalid"
            )
        return parsed

    def _build_receipt(
        self,
        request: ExecutorWorkspaceProvisionRequest,
        binding: dict[str, str],
        observed: dict[str, str],
    ) -> dict[str, str]:
        if (
            observed["OPENZYME_RUNNER_HANDLE"] != binding["runner_handle"]
            or observed["OPENZYME_INTENT_DIGEST"] != request.intent_digest
            or observed["OPENZYME_WORKSPACE_PATH"]
            != binding["remote_workspace_path"]
            or observed["OPENZYME_BASE_COMMIT"] != request.base_commit
            or observed["OPENZYME_OWNER_DIGEST"] != request.owner_identity_digest
            or _DIGEST.fullmatch(
                observed["OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST"]
            )
            is None
            or _DIGEST.fullmatch(observed["OPENZYME_ISOLATION_RECEIPT_DIGEST"])
            is None
        ):
            raise ExecutorWorkspaceProvisionError(
                "remote workspace receipt identity conflicts with frozen binding"
            )
        root_digest = self._digest(
            {
                "target_profile_digest": request.target_profile_digest,
                "workspace_path": binding["remote_workspace_path"],
                "runner_handle": binding["runner_handle"],
            }
        )
        payload = {
            "schema_version": _PROVISION_RECEIPT_SCHEMA_VERSION,
            "receipt_id": "hpcprovision_" + request.intent_digest[-32:],
            "intent_id": request.intent_id,
            "intent_digest": request.intent_digest,
            "workspace_id": request.workspace_id,
            "runner_handle": binding["runner_handle"],
            "target_profile_digest": request.target_profile_digest,
            "login_alias": self.config.executor_workspace.login_alias,
            "remote_workspace_path": binding["remote_workspace_path"],
            "remote_root_digest": root_digest,
            "repository_remote_digest": request.repository_remote_digest,
            "clone_head_commit": request.base_commit,
            "owner_identity_digest": request.owner_identity_digest,
            "os_principal_identity_digest": observed[
                "OPENZYME_OS_PRINCIPAL_IDENTITY_DIGEST"
            ],
            "isolation_receipt_digest": observed[
                "OPENZYME_ISOLATION_RECEIPT_DIGEST"
            ],
            "created_at": observed["OPENZYME_CREATED_AT"],
        }
        return {**payload, "receipt_digest": self._digest(payload)}

    def _build_cleanup_receipt(
        self,
        request: ExecutorWorkspaceCleanupRequest,
        binding: dict[str, str],
        provision_receipt: dict[str, str],
        observed: dict[str, str],
    ) -> dict[str, Any]:
        provision = request.provision_request
        if (
            observed["OPENZYME_CLEANUP_RUNNER_HANDLE"]
            != binding["runner_handle"]
            or observed["OPENZYME_PROVISION_INTENT_DIGEST"]
            != provision.intent_digest
            or observed["OPENZYME_CLEANUP_INTENT_ID"]
            != request.cleanup_intent_id
            or observed["OPENZYME_CLEANUP_INTENT_DIGEST"]
            != request.cleanup_intent_digest
            or observed["OPENZYME_CLEANUP_ROOT_DIGEST"]
            != provision_receipt["remote_root_digest"]
            or observed["OPENZYME_SETTLEMENT_PROOF_DIGEST"]
            != request.settlement_proof_digest
            or observed["OPENZYME_CLEANUP_DISPOSITION"] != "deleted"
            or _DIGEST.fullmatch(
                observed["OPENZYME_ISOLATION_CLEANUP_RECEIPT_DIGEST"]
            )
            is None
        ):
            raise ExecutorWorkspaceProvisionError(
                "remote cleanup receipt conflicts with frozen intent"
            )
        payload = {
            "schema_version": _CLEANUP_RECEIPT_SCHEMA_VERSION,
            "cleanup_receipt_id": (
                "hpccleanup_" + request.cleanup_intent_digest[-32:]
            ),
            "cleanup_intent_id": request.cleanup_intent_id,
            "cleanup_intent_digest": request.cleanup_intent_digest,
            "workspace_id": provision.workspace_id,
            "runner_handle": binding["runner_handle"],
            "remote_root_digest": provision_receipt["remote_root_digest"],
            "disposition": "deleted",
            "unsettled_effect_count": 0,
            "settlement_proof_digest": request.settlement_proof_digest,
            "isolation_cleanup_receipt_digest": observed[
                "OPENZYME_ISOLATION_CLEANUP_RECEIPT_DIGEST"
            ],
            "created_at": observed["OPENZYME_CLEANUP_CREATED_AT"],
        }
        return {**payload, "receipt_digest": self._digest(payload)}

    def _read_receipt(self, binding: dict[str, str]) -> dict[str, str] | None:
        path = self._receipt_path(binding["intent_digest"])
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        expected = {
            "schema_version",
            "receipt_id",
            "intent_id",
            "intent_digest",
            "workspace_id",
            "runner_handle",
            "target_profile_digest",
            "login_alias",
            "remote_workspace_path",
            "remote_root_digest",
            "repository_remote_digest",
            "clone_head_commit",
            "owner_identity_digest",
            "os_principal_identity_digest",
            "isolation_receipt_digest",
            "created_at",
            "receipt_digest",
        }
        if (
            not isinstance(raw, dict)
            or set(raw) != expected
            or any(not isinstance(raw[key], str) for key in expected)
            or raw.get("schema_version") != _PROVISION_RECEIPT_SCHEMA_VERSION
            or raw.get("intent_digest") != binding["intent_digest"]
            or raw.get("runner_handle") != binding["runner_handle"]
            or raw.get("remote_workspace_path")
            != binding["remote_workspace_path"]
            or _DIGEST.fullmatch(raw["receipt_digest"]) is None
            or raw["receipt_digest"]
            != self._digest(
                {key: raw[key] for key in expected if key != "receipt_digest"}
            )
        ):
            raise ExecutorWorkspaceProvisionError(
                "executor workspace local receipt identity drifted"
            )
        return dict(raw)

    def _write_receipt_once(
        self,
        binding: dict[str, str],
        receipt: dict[str, str],
    ) -> None:
        path = self._receipt_path(binding["intent_digest"])
        try:
            self._write_json_once(path, receipt)
        except FileExistsError:
            if self._read_receipt(binding) != receipt:
                raise ExecutorWorkspaceProvisionError(
                    "executor workspace local receipt conflicts"
                )

    def _read_cleanup_receipt(
        self,
        binding: dict[str, str],
        request: ExecutorWorkspaceCleanupRequest,
    ) -> dict[str, Any] | None:
        path = self._cleanup_receipt_path(binding["intent_digest"])
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        expected = {
            "schema_version",
            "cleanup_receipt_id",
            "cleanup_intent_id",
            "cleanup_intent_digest",
            "workspace_id",
            "runner_handle",
            "remote_root_digest",
            "disposition",
            "unsettled_effect_count",
            "settlement_proof_digest",
            "isolation_cleanup_receipt_digest",
            "created_at",
            "receipt_digest",
        }
        if (
            not isinstance(raw, dict)
            or set(raw) != expected
            or any(
                not isinstance(raw[key], str)
                for key in expected - {"unsettled_effect_count"}
            )
            or raw.get("unsettled_effect_count") != 0
            or raw.get("schema_version") != _CLEANUP_RECEIPT_SCHEMA_VERSION
            or raw.get("cleanup_intent_id") != request.cleanup_intent_id
            or raw.get("cleanup_intent_digest") != request.cleanup_intent_digest
            or raw.get("workspace_id") != request.provision_request.workspace_id
            or raw.get("runner_handle") != binding["runner_handle"]
            or raw.get("settlement_proof_digest")
            != request.settlement_proof_digest
            or _DIGEST.fullmatch(raw["receipt_digest"]) is None
            or raw["receipt_digest"]
            != self._digest(
                {key: raw[key] for key in expected if key != "receipt_digest"}
            )
        ):
            raise ExecutorWorkspaceProvisionError(
                "executor workspace local cleanup receipt identity drifted"
            )
        return dict(raw)

    def _write_cleanup_receipt_once(
        self,
        binding: dict[str, str],
        request: ExecutorWorkspaceCleanupRequest,
        receipt: dict[str, Any],
    ) -> None:
        path = self._cleanup_receipt_path(binding["intent_digest"])
        try:
            self._write_json_once(path, receipt)
        except FileExistsError:
            if self._read_cleanup_receipt(binding, request) != receipt:
                raise ExecutorWorkspaceProvisionError(
                    "executor workspace local cleanup receipt conflicts"
                )

    def _prepare_state_root(self) -> None:
        self._state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        state = self._state_root.stat()
        if (
            self._state_root.is_symlink()
            or not stat.S_ISDIR(state.st_mode)
            or state.st_uid != os.geteuid()
            or state.st_mode & 0o077
        ):
            raise ExecutorWorkspaceProvisionError(
                "executor workspace private state root ownership mode is unsafe"
            )

    def _binding_path(self, intent_digest: str) -> Path:
        return self._state_root / (
            intent_digest.removeprefix("sha256:") + ".binding.json"
        )

    def _workspace_index_path(self, workspace_id: str, generation: int) -> Path:
        if (
            _IDENTIFIER.fullmatch(workspace_id) is None
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
        ):
            raise ExecutorWorkspaceProvisionError(
                "executor workspace index identity is invalid"
            )
        return self._state_root / f"{workspace_id}.g{generation}.index.json"

    def _receipt_path(self, intent_digest: str) -> Path:
        return self._state_root / (
            intent_digest.removeprefix("sha256:") + ".receipt.json"
        )

    def _cleanup_receipt_path(self, intent_digest: str) -> Path:
        return self._state_root / (
            intent_digest.removeprefix("sha256:") + ".cleanup.json"
        )

    @staticmethod
    def _remote_cleanup_path(binding: dict[str, str]) -> str:
        return binding["remote_sidecar_path"] + ".cleanup"

    @staticmethod
    def _write_json_once(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
        path.chmod(0o600)

    @staticmethod
    def _digest(payload: object) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ExecutorWorkspaceCleanupRequest",
    "ExecutorWorkspaceProvisionError",
    "ExecutorWorkspaceProvisionInDoubt",
    "ExecutorWorkspaceProvisionRequest",
    "ExecutorWorkspaceProvisioningService",
]
