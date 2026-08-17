from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
from typing import Protocol

from mcp_hpc_runner.executor_workspaces import ExecutorWorkspaceProvisionInDoubt
from mcp_hpc_runner.executor_workspaces import ExecutorWorkspaceProvisionError
from mcp_hpc_runner.executor_workspaces import ExecutorWorkspaceCleanupRequest
from mcp_hpc_runner.executor_workspaces import ExecutorWorkspaceProvisionRequest
from openzyme_core import CoreRepositories
from openzyme_core import ExecutorHpcWorkspaceDispatchInDoubt
from openzyme_core import ExecutorHpcWorkspaceIdentityConflict
from openzyme_core import ExecutorHpcNativeQualificationEvidence
from openzyme_core import ExecutorHpcWorkspaceObservation
from openzyme_core import ExecutorHpcWorkspaceObservationKind
from openzyme_core import ExecutorHpcWorkspaceProvisioningRequired
from openzyme_core import IssuedExecutorHpcCredential
from openzyme_domain import ExecutorHpcCleanupDisposition
from openzyme_domain import ExecutorHpcCredentialClaim
from openzyme_domain import ExecutorHpcWorkspaceProvisionIntent
from openzyme_domain import ExecutorHpcWorkspaceProvisionReceipt
from openzyme_domain import ExecutorHpcWorkspace
from openzyme_domain import ExecutorHpcWorkspaceCleanupIntent
from openzyme_domain import ExecutorHpcWorkspaceCleanupReceipt
from openzyme_domain import canonical_executor_hpc_digest


_ISSUE_RESULT_SCHEMA_VERSION = "executor_hpc_credential_provider_result@1"
_REVOKE_RESULT_SCHEMA_VERSION = "executor_hpc_credential_revoke_result@1"


class ExecutorHpcRunnerServer(Protocol):
    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None,
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class McpExecutorHpcWorkspaceProvisioner:
    repositories: CoreRepositories
    server: ExecutorHpcRunnerServer

    def provision(
        self,
        intent: ExecutorHpcWorkspaceProvisionIntent,
    ) -> ExecutorHpcWorkspaceProvisionReceipt:
        request = self._request(intent)
        raw = self._call_runner("workspace.provision", request.to_dict())
        return self._receipt(raw, intent=intent)

    def reconcile(
        self,
        intent: ExecutorHpcWorkspaceProvisionIntent,
    ) -> ExecutorHpcWorkspaceProvisionReceipt | None:
        request = self._request(intent)
        raw = self._call_runner("workspace.inspect", request.to_dict())
        expected = {"schema_version", "workspace", "replacement_created"}
        if (
            not isinstance(raw, dict)
            or set(raw) != expected
            or raw["schema_version"] != "executor_workspace_inspection@1"
            or raw["replacement_created"] is not False
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner returned an invalid same-handle inspection"
            )
        workspace = raw["workspace"]
        if workspace is None:
            return None
        if not isinstance(workspace, dict):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner inspection receipt is not an object"
            )
        return self._receipt(workspace, intent=intent)

    def cleanup(
        self,
        workspace: ExecutorHpcWorkspace,
        intent: ExecutorHpcWorkspaceProvisionIntent,
        cleanup_intent: ExecutorHpcWorkspaceCleanupIntent,
    ) -> ExecutorHpcWorkspaceCleanupReceipt:
        request = self._cleanup_request(workspace, intent, cleanup_intent)
        raw = self._call_runner("workspace.cleanup", request.to_dict())
        return self._cleanup_receipt(raw, cleanup_intent=cleanup_intent)

    def reconcile_cleanup(
        self,
        workspace: ExecutorHpcWorkspace,
        intent: ExecutorHpcWorkspaceProvisionIntent,
        cleanup_intent: ExecutorHpcWorkspaceCleanupIntent,
    ) -> ExecutorHpcWorkspaceCleanupReceipt | None:
        request = self._cleanup_request(workspace, intent, cleanup_intent)
        raw = self._call_runner("workspace.cleanup.inspect", request.to_dict())
        if (
            not isinstance(raw, dict)
            or set(raw)
            != {"schema_version", "cleanup", "replacement_targeted"}
            or raw["schema_version"]
            != "executor_workspace_cleanup_inspection@1"
            or raw["replacement_targeted"] is not False
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner returned an invalid exact cleanup inspection"
            )
        cleanup = raw["cleanup"]
        if cleanup is None:
            return None
        if not isinstance(cleanup, dict):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner cleanup inspection receipt is not an object"
            )
        return self._cleanup_receipt(
            cleanup,
            cleanup_intent=cleanup_intent,
        )

    def inspect_state(
        self,
        intent: ExecutorHpcWorkspaceProvisionIntent,
        workspace: ExecutorHpcWorkspace,
    ) -> ExecutorHpcWorkspaceObservation:
        raw = self._call_runner(
            "workspace.verify",
            self._request(intent).to_dict(),
        )
        expected = {
            "schema_version",
            "workspace_id",
            "intent_digest",
            "runner_handle",
            "remote_root_digest",
            "kind",
            "repository_remote_digest",
            "head_commit",
            "independent_git_directory",
            "protected_root_mode",
            "os_principal_identity_digest",
            "isolation_receipt_digest",
            "observed_at",
            "observation_digest",
        }
        if not isinstance(raw, dict) or set(raw) != expected:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner workspace observation fields are incomplete or unknown"
            )
        values = {
            key: raw[key]
            for key in expected
            if key not in {"schema_version", "observation_digest", "kind"}
        }
        try:
            observation = ExecutorHpcWorkspaceObservation.create(
                **values,
                kind=ExecutorHpcWorkspaceObservationKind(raw["kind"]),
            )
        except (TypeError, ValueError) as exc:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner workspace observation values are invalid"
            ) from exc
        if (
            raw["schema_version"] != observation.schema_version
            or raw["observation_digest"] != observation.observation_digest
            or observation.workspace_id != workspace.workspace_id
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner workspace observation identity drifted"
            )
        return observation

    def _call_runner(
        self,
        tool_name: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self.server.call_tool(tool_name, {"request": request})
        except ExecutorWorkspaceProvisionInDoubt as exc:
            raise ExecutorHpcWorkspaceDispatchInDoubt(str(exc)) from exc
        except ExecutorWorkspaceProvisionError as exc:
            raise ExecutorHpcWorkspaceProvisioningRequired(str(exc)) from exc
        except ValueError as exc:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner rejected the closed executor workspace request"
            ) from exc

    def _request(
        self,
        intent: ExecutorHpcWorkspaceProvisionIntent,
    ) -> ExecutorWorkspaceProvisionRequest:
        binding = self.repositories.project_repository_bindings.get(
            intent.repository_binding_id
        )
        if (
            binding is None
            or binding.binding_version != intent.repository_binding_version
            or binding.repository_id != intent.repository_id
            or binding.default_base_commit != intent.base_commit
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "provision intent repository binding is not exact current source"
            )
        owner_digest = canonical_executor_hpc_digest(
            {
                "session_id": intent.session_id,
                "executor_agent_member_id": intent.executor_agent_member_id,
                "local_workspace_generation": intent.local_workspace_generation,
                "remote_workspace_generation": intent.remote_workspace_generation,
                "capability_lease_id": intent.capability_lease_id,
                "capability_lease_version": intent.capability_lease_version,
            }
        )
        return ExecutorWorkspaceProvisionRequest(
            intent_id=intent.intent_id,
            intent_digest=intent.intent_digest,
            workspace_id=intent.workspace_id,
            remote_workspace_generation=intent.remote_workspace_generation,
            target_profile_digest=intent.target_profile_digest,
            repository_endpoint=binding.internal_git_endpoint,
            repository_remote_digest=binding.canonical_digest,
            base_commit=intent.base_commit,
            owner_identity_digest=owner_digest,
            idempotency_key=intent.idempotency_key,
            absolute_deadline=intent.absolute_deadline,
        )

    def _cleanup_request(
        self,
        workspace: ExecutorHpcWorkspace,
        intent: ExecutorHpcWorkspaceProvisionIntent,
        cleanup_intent: ExecutorHpcWorkspaceCleanupIntent,
    ) -> ExecutorWorkspaceCleanupRequest:
        if (
            cleanup_intent.workspace_id != workspace.workspace_id
            or cleanup_intent.runner_handle != workspace.runner_handle
            or cleanup_intent.remote_root_digest != workspace.remote_root_digest
            or intent.workspace_id != workspace.workspace_id
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "cleanup intent differs from exact workspace/provision identity"
            )
        return ExecutorWorkspaceCleanupRequest(
            provision_request=self._request(intent),
            cleanup_intent_id=cleanup_intent.cleanup_intent_id,
            cleanup_intent_digest=cleanup_intent.intent_digest,
            workspace_state_version=cleanup_intent.workspace_state_version,
            settlement_proof_digest=cleanup_intent.settlement_proof_digest,
            idempotency_key=cleanup_intent.idempotency_key,
            unsettled_effect_count=0,
        )

    @staticmethod
    def _receipt(
        raw: dict[str, Any],
        *,
        intent: ExecutorHpcWorkspaceProvisionIntent,
    ) -> ExecutorHpcWorkspaceProvisionReceipt:
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
        if not isinstance(raw, dict) or set(raw) != expected:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner provision receipt fields are incomplete or unknown"
            )
        values = {
            key: raw[key]
            for key in expected
            if key not in {"schema_version", "receipt_digest"}
        }
        if not all(isinstance(value, str) for value in values.values()):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner provision receipt fields must be strings"
            )
        receipt = ExecutorHpcWorkspaceProvisionReceipt.create(**values)
        if (
            raw["schema_version"] != receipt.schema_version
            or raw["receipt_digest"] != receipt.receipt_digest
            or receipt.intent_id != intent.intent_id
            or receipt.intent_digest != intent.intent_digest
            or receipt.workspace_id != intent.workspace_id
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner provision receipt identity drifted from exact intent"
            )
        return receipt

    @staticmethod
    def _cleanup_receipt(
        raw: dict[str, Any],
        *,
        cleanup_intent: ExecutorHpcWorkspaceCleanupIntent,
    ) -> ExecutorHpcWorkspaceCleanupReceipt:
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
        if not isinstance(raw, dict) or set(raw) != expected:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner cleanup receipt fields are incomplete or unknown"
            )
        values = {
            key: raw[key]
            for key in expected
            if key not in {"schema_version", "receipt_digest"}
        }
        try:
            values["disposition"] = ExecutorHpcCleanupDisposition(
                values["disposition"]
            )
            receipt = ExecutorHpcWorkspaceCleanupReceipt.create(**values)
        except (TypeError, ValueError) as exc:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner cleanup receipt values are invalid"
            ) from exc
        if (
            raw["schema_version"] != receipt.schema_version
            or raw["receipt_digest"] != receipt.receipt_digest
            or receipt.cleanup_intent_id != cleanup_intent.cleanup_intent_id
            or receipt.cleanup_intent_digest != cleanup_intent.intent_digest
            or receipt.workspace_id != cleanup_intent.workspace_id
            or receipt.settlement_proof_digest
            != cleanup_intent.settlement_proof_digest
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "runner cleanup receipt drifted from immutable cleanup intent"
            )
        return receipt


@dataclass(frozen=True, slots=True)
class ExecutorHpcCredentialCommandResult:
    returncode: int
    stdout: str
    stderr: str


class ExecutorHpcCredentialCommandExecutor(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        stdin: str,
        timeout_seconds: int,
    ) -> ExecutorHpcCredentialCommandResult: ...


@dataclass(slots=True)
class CommandExecutorHpcQualificationEvidenceVerifier:
    verifier_command: tuple[str, ...]
    executor: ExecutorHpcCredentialCommandExecutor
    timeout_seconds: int = 300

    def __post_init__(self) -> None:
        if (
            not self.verifier_command
            or not Path(self.verifier_command[0]).is_absolute()
            or any(not value or "\x00" in value for value in self.verifier_command)
        ):
            raise ValueError(
                "native qualification verifier must use an absolute closed argv"
            )
        if self.timeout_seconds <= 0 or self.timeout_seconds > 3600:
            raise ValueError(
                "native qualification verifier timeout must be between 1 and 3600"
            )

    def verify(self, evidence: ExecutorHpcNativeQualificationEvidence) -> str:
        request = {
            "schema_version": "executor_hpc_native_qualification_verify_request@1",
            "evidence": evidence.payload,
            "evidence_digest": evidence.evidence_digest,
        }
        result = self.executor.run(
            self.verifier_command,
            stdin=json.dumps(
                request,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            timeout_seconds=self.timeout_seconds,
        )
        if result.returncode != 0:
            diagnostic_digest = hashlib.sha256(
                result.stderr.encode("utf-8", errors="replace")
            ).hexdigest()
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "native qualification verifier failed: "
                f"exit={result.returncode} stderr_sha256={diagnostic_digest}"
            )
        try:
            raw = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "native qualification verifier returned invalid JSON"
            ) from exc
        if (
            not isinstance(raw, dict)
            or set(raw)
            != {
                "schema_version",
                "evidence_digest",
                "verification_receipt_digest",
                "verified",
            }
            or raw["schema_version"]
            != "executor_hpc_native_qualification_verify_result@1"
            or raw["evidence_digest"] != evidence.evidence_digest
            or raw["verified"] is not True
            or not _is_digest(raw["verification_receipt_digest"])
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "native qualification verifier did not attest exact evidence"
            )
        return evidence.evidence_digest


@dataclass(slots=True)
class SubprocessExecutorHpcCredentialCommandExecutor:
    def run(
        self,
        argv: tuple[str, ...],
        *,
        stdin: str,
        timeout_seconds: int,
    ) -> ExecutorHpcCredentialCommandResult:
        completed = subprocess.run(
            argv,
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            env={"PATH": "/usr/bin:/bin"},
        )
        return ExecutorHpcCredentialCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass(slots=True)
class CommandExecutorHpcCredentialProvider:
    provider_id: str
    authenticator_id: str
    issue_command: tuple[str, ...]
    revoke_command: tuple[str, ...]
    executor: ExecutorHpcCredentialCommandExecutor
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        for name, command in (
            ("issue_command", self.issue_command),
            ("revoke_command", self.revoke_command),
        ):
            if (
                not command
                or not Path(command[0]).is_absolute()
                or any(not value or "\x00" in value for value in command)
            ):
                raise ValueError(f"{name} must use an absolute closed argv")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 300:
            raise ValueError("credential command timeout must be between 1 and 300")

    def issue(
        self,
        claim: ExecutorHpcCredentialClaim,
    ) -> IssuedExecutorHpcCredential:
        if (
            claim.credential_provider_id != self.provider_id
            or claim.authenticator_id != self.authenticator_id
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "credential command identity differs from exact target claim"
            )
        claim_payload = claim.to_dict()
        request = {
            "schema_version": "executor_hpc_credential_provider_request@1",
            "provider_id": self.provider_id,
            "authenticator_id": self.authenticator_id,
            "claim": claim_payload,
            "claim_digest": canonical_executor_hpc_digest(claim_payload),
            "scheduler_submit_authorized": False,
        }
        raw = self._run_json(self.issue_command, request)
        expected = {
            "schema_version",
            "provider_id",
            "authenticator_id",
            "claim_digest",
            "credential_fingerprint",
            "authentication_receipt_digest",
            "authenticated",
            "environment",
            "exact_secret_material",
        }
        if not isinstance(raw, dict) or set(raw) != expected:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "credential provider result fields are incomplete or unknown"
            )
        if (
            raw["schema_version"] != _ISSUE_RESULT_SCHEMA_VERSION
            or raw["provider_id"] != self.provider_id
            or raw["authenticator_id"] != self.authenticator_id
            or raw["claim_digest"] != request["claim_digest"]
            or raw["authenticated"] is not True
            or not isinstance(raw["environment"], dict)
            or not isinstance(raw["exact_secret_material"], list)
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "credential provider did not authenticate the exact claim"
            )
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw["environment"].items()
        ) or not all(
            isinstance(value, str) and value
            for value in raw["exact_secret_material"]
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "credential provider returned invalid process material"
            )
        return IssuedExecutorHpcCredential(
            claim=claim,
            credential_fingerprint=str(raw["credential_fingerprint"]),
            authentication_receipt_digest=str(
                raw["authentication_receipt_digest"]
            ),
            environment=tuple(sorted(raw["environment"].items())),
            exact_secret_material=tuple(raw["exact_secret_material"]),
        )

    def revoke(self, credential_fingerprint: str) -> None:
        request = {
            "schema_version": "executor_hpc_credential_revoke_request@1",
            "provider_id": self.provider_id,
            "authenticator_id": self.authenticator_id,
            "credential_fingerprint": credential_fingerprint,
        }
        raw = self._run_json(self.revoke_command, request)
        expected = {
            "schema_version",
            "provider_id",
            "authenticator_id",
            "credential_fingerprint",
            "revoked",
            "revoke_receipt_digest",
        }
        if (
            not isinstance(raw, dict)
            or set(raw) != expected
            or raw["schema_version"] != _REVOKE_RESULT_SCHEMA_VERSION
            or raw["provider_id"] != self.provider_id
            or raw["authenticator_id"] != self.authenticator_id
            or raw["credential_fingerprint"] != credential_fingerprint
            or raw["revoked"] is not True
            or not _is_digest(raw["revoke_receipt_digest"])
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "credential provider did not confirm exact revocation"
            )

    def _run_json(
        self,
        argv: tuple[str, ...],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        result = self.executor.run(
            argv,
            stdin=encoded,
            timeout_seconds=self.timeout_seconds,
        )
        if result.returncode != 0:
            diagnostic_digest = hashlib.sha256(
                result.stderr.encode("utf-8", errors="replace")
            ).hexdigest()
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "credential provider command failed: "
                f"exit={result.returncode} stderr_sha256={diagnostic_digest}"
            )
        try:
            value = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "credential provider returned invalid JSON"
            ) from exc
        if not isinstance(value, dict):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "credential provider result must be an object"
            )
        return value


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


__all__ = [
    "CommandExecutorHpcQualificationEvidenceVerifier",
    "CommandExecutorHpcCredentialProvider",
    "ExecutorHpcCredentialCommandExecutor",
    "ExecutorHpcCredentialCommandResult",
    "McpExecutorHpcWorkspaceProvisioner",
    "SubprocessExecutorHpcCredentialCommandExecutor",
]
