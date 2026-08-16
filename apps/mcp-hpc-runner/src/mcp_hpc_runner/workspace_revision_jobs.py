from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
from typing import Any

from .config import RunnerConfig
from .models import ExecutorWorkspaceRunSpec
from .transport import SshTransportManager


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_PREPARE_SCHEMA = "workspace_revision_source_prepare_request@1"
_QUALIFICATION_SCHEMA = "workspace_job_runner_target_qualification@1"
_CREDENTIAL_SCHEMA = "scheduler_occurrence_credential@1"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _require_exact_object(
    value: object,
    *,
    fields: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} fields are closed")
    return value


@dataclass(frozen=True, slots=True)
class WorkspaceRevisionSourcePrepareRequest:
    request_id: str
    workspace_id: str
    remote_workspace_generation: int
    repository_binding_id: str
    repository_binding_version: int
    repository_binding_digest: str
    repository_policy_digest: str
    target_profile_digest: str
    runner_policy_digest: str
    source_commit: str
    source_tree: str
    source_ref: str
    lfs_closure_manifest_digest: str
    toolchain_digest: str
    owner_identity_digest: str
    absolute_deadline: str
    request_digest: str
    schema_version: str = _PREPARE_SCHEMA

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
    ) -> "WorkspaceRevisionSourcePrepareRequest":
        fields = frozenset(
            {
                "schema_version",
                "request_id",
                "workspace_id",
                "remote_workspace_generation",
                "repository_binding_id",
                "repository_binding_version",
                "repository_binding_digest",
                "repository_policy_digest",
                "target_profile_digest",
                "runner_policy_digest",
                "source_commit",
                "source_tree",
                "source_ref",
                "lfs_closure_manifest_digest",
                "toolchain_digest",
                "owner_identity_digest",
                "absolute_deadline",
                "request_digest",
            }
        )
        data = _require_exact_object(value, fields=fields, label="source prepare request")
        if data["schema_version"] != _PREPARE_SCHEMA:
            raise ValueError("source prepare request schema is unsupported")
        return cls(**data)

    def __post_init__(self) -> None:
        for name in ("request_id", "workspace_id", "repository_binding_id"):
            if _IDENTIFIER.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"source prepare {name} is invalid")
        for name in ("remote_workspace_generation", "repository_binding_version"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"source prepare {name} must be positive")
        for name in (
            "repository_binding_digest",
            "repository_policy_digest",
            "target_profile_digest",
            "runner_policy_digest",
            "lfs_closure_manifest_digest",
            "toolchain_digest",
            "owner_identity_digest",
            "request_digest",
        ):
            if _DIGEST.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"source prepare {name} is invalid")
        for name in ("source_commit", "source_tree"):
            if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", getattr(self, name)) is None:
                raise ValueError(f"source prepare {name} is invalid")
        if not self.source_ref.startswith("refs/"):
            raise ValueError("source prepare ref is not exact")
        parsed = datetime.fromisoformat(self.absolute_deadline)
        if parsed.tzinfo is None:
            raise ValueError("source prepare deadline must include timezone")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "workspace_id": self.workspace_id,
            "remote_workspace_generation": self.remote_workspace_generation,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_binding_digest": self.repository_binding_digest,
            "repository_policy_digest": self.repository_policy_digest,
            "target_profile_digest": self.target_profile_digest,
            "runner_policy_digest": self.runner_policy_digest,
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "source_ref": self.source_ref,
            "lfs_closure_manifest_digest": self.lfs_closure_manifest_digest,
            "toolchain_digest": self.toolchain_digest,
            "owner_identity_digest": self.owner_identity_digest,
            "absolute_deadline": self.absolute_deadline,
            "request_digest": self.request_digest,
        }


@dataclass(frozen=True, slots=True)
class SchedulerOccurrenceCredential:
    occurrence_id: str
    dispatch_id: str
    execution_id: str
    target_profile_digest: str
    reservation_nonce_digest: str
    scheduler_marker: str
    payload_digest: str
    protected_wrapper_audience: str
    expires_at: str
    opaque_token: str
    schema_version: str = _CREDENTIAL_SCHEMA

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SchedulerOccurrenceCredential":
        fields = frozenset(
            {
                "schema_version",
                "occurrence_id",
                "dispatch_id",
                "execution_id",
                "target_profile_digest",
                "reservation_nonce_digest",
                "scheduler_marker",
                "payload_digest",
                "protected_wrapper_audience",
                "expires_at",
                "opaque_token",
            }
        )
        data = _require_exact_object(value, fields=fields, label="scheduler credential")
        if data["schema_version"] != _CREDENTIAL_SCHEMA:
            raise ValueError("scheduler credential schema is unsupported")
        return cls(**data)

    def __post_init__(self) -> None:
        for name in (
            "occurrence_id",
            "dispatch_id",
            "execution_id",
            "scheduler_marker",
            "protected_wrapper_audience",
        ):
            if _IDENTIFIER.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"scheduler credential {name} is invalid")
        for name in (
            "target_profile_digest",
            "reservation_nonce_digest",
            "payload_digest",
        ):
            if _DIGEST.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"scheduler credential {name} is invalid")
        if not self.opaque_token or any(char.isspace() for char in self.opaque_token):
            raise ValueError("scheduler credential token is invalid")
        parsed = datetime.fromisoformat(self.expires_at)
        if parsed.tzinfo is None:
            raise ValueError("scheduler credential expiry must include timezone")

    def to_private_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "occurrence_id": self.occurrence_id,
            "dispatch_id": self.dispatch_id,
            "execution_id": self.execution_id,
            "target_profile_digest": self.target_profile_digest,
            "reservation_nonce_digest": self.reservation_nonce_digest,
            "scheduler_marker": self.scheduler_marker,
            "payload_digest": self.payload_digest,
            "protected_wrapper_audience": self.protected_wrapper_audience,
            "expires_at": self.expires_at,
            "opaque_token": self.opaque_token,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceJobRunnerQualification:
    target_profile_digest: str
    runner_policy_digest: str
    toolchain_digest: str
    protected_wrapper_path: str
    protected_wrapper_digest: str
    dispatch_ledger_digest: str
    scheduler_credential_audience: str
    slurm_enabled: bool
    direct_enabled: bool
    ambient_submit_denial_proof_digest: str
    scheduler_accounting_proof_digest: str
    direct_terminal_proof_digest: str
    qualification_digest: str
    schema_version: str = _QUALIFICATION_SCHEMA

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkspaceJobRunnerQualification":
        fields = frozenset(cls.__dataclass_fields__)
        data = _require_exact_object(value, fields=fields, label="runner qualification")
        if data["schema_version"] != _QUALIFICATION_SCHEMA:
            raise ValueError("runner qualification schema is unsupported")
        return cls(**data)

    def __post_init__(self) -> None:
        for name in (
            "target_profile_digest",
            "runner_policy_digest",
            "toolchain_digest",
            "protected_wrapper_digest",
            "dispatch_ledger_digest",
            "ambient_submit_denial_proof_digest",
            "scheduler_accounting_proof_digest",
            "direct_terminal_proof_digest",
            "qualification_digest",
        ):
            if _DIGEST.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"runner qualification {name} is invalid")
        wrapper = Path(self.protected_wrapper_path)
        if not wrapper.is_absolute() or any(char.isspace() for char in self.protected_wrapper_path):
            raise ValueError("protected wrapper path must be absolute and canonical")
        if not (self.slurm_enabled or self.direct_enabled):
            raise ValueError("runner qualification enables no reliable mode")
        payload = {
            key: value
            for key, value in self.to_dict().items()
            if key != "qualification_digest"
        }
        if self.qualification_digest != _digest(payload):
            raise ValueError("runner qualification digest mismatch")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target_profile_digest": self.target_profile_digest,
            "runner_policy_digest": self.runner_policy_digest,
            "toolchain_digest": self.toolchain_digest,
            "protected_wrapper_path": self.protected_wrapper_path,
            "protected_wrapper_digest": self.protected_wrapper_digest,
            "dispatch_ledger_digest": self.dispatch_ledger_digest,
            "scheduler_credential_audience": self.scheduler_credential_audience,
            "slurm_enabled": self.slurm_enabled,
            "direct_enabled": self.direct_enabled,
            "ambient_submit_denial_proof_digest": (
                self.ambient_submit_denial_proof_digest
            ),
            "scheduler_accounting_proof_digest": (
                self.scheduler_accounting_proof_digest
            ),
            "direct_terminal_proof_digest": self.direct_terminal_proof_digest,
            "qualification_digest": self.qualification_digest,
        }


class WorkspaceRevisionJobError(RuntimeError):
    error_code = "workspace_revision_job_error"


class WorkspaceRevisionJobInDoubt(WorkspaceRevisionJobError):
    error_code = "workspace_revision_job_dispatch_in_doubt"


class WorkspaceRevisionJobNoEffect(WorkspaceRevisionJobError):
    error_code = "workspace_revision_job_no_effect"


class WorkspaceRevisionJobService:
    """Invoke only an operator-qualified remote wrapper and preserve one ledger."""

    def __init__(self, config: RunnerConfig, transport: SshTransportManager) -> None:
        self.config = config
        self.transport = transport
        self._lock = threading.RLock()
        self._root = config.control_root / "workspace-revision-jobs"

    def prepare_source(
        self,
        request: WorkspaceRevisionSourcePrepareRequest,
    ) -> dict[str, Any]:
        self._require_before_deadline(request.absolute_deadline)
        qualification = self._qualification(
            target_profile_digest=request.target_profile_digest,
            runner_policy_digest=request.runner_policy_digest,
            toolchain_digest=request.toolchain_digest,
        )
        response = self._invoke_wrapper(
            qualification,
            "prepare-source",
            request.to_dict(),
            stage="workspace_source_prepare",
        )
        manifest = self._validate_manifest_response(request, response)
        with self._lock:
            self._write_once(
                self._record_path("sources", request.request_id),
                manifest,
            )
        return manifest

    def dispatch(
        self,
        spec: ExecutorWorkspaceRunSpec,
        *,
        scheduler_credential: SchedulerOccurrenceCredential | None = None,
    ) -> dict[str, Any]:
        self._require_before_deadline(spec.absolute_deadline)
        qualification = self._qualification(
            target_profile_digest=spec.target_profile_digest,
            runner_policy_digest=spec.runner_policy_digest,
            toolchain_digest=spec.toolchain_digest,
        )
        if spec.selected_mode == "sbatch":
            if not qualification.slurm_enabled or scheduler_credential is None:
                raise WorkspaceRevisionJobError(
                    "Slurm mode lacks exact target qualification or credential"
                )
            self._validate_scheduler_credential(
                spec=spec,
                qualification=qualification,
                credential=scheduler_credential,
            )
        elif scheduler_credential is not None or not qualification.direct_enabled:
            raise WorkspaceRevisionJobError(
                "direct mode rejects scheduler credential or lacks qualification"
            )
        intent = self._dispatch_identity(spec)
        intent_path = self._record_path("dispatch-intents", spec.dispatch_id)
        handle_path = self._record_path("handles", spec.dispatch_id)
        with self._lock:
            self._write_once(
                self._record_path("runspecs", spec.runner_run_id),
                spec.to_dict(),
            )
            self._write_once(intent_path, intent)
            existing = self._read_optional(handle_path)
            if existing is not None:
                return existing
        body: dict[str, object] = {"runspec": spec.to_dict()}
        if scheduler_credential is not None:
            body["scheduler_credential"] = scheduler_credential.to_private_dict()
        try:
            result = self.transport.run_ssh(
                [qualification.protected_wrapper_path, "dispatch", "--stdin-json"],
                check=False,
                timeout=self.config.execution.remote_execution_timeout_seconds,
                stage="workspace_job_dispatch",
                input_text=_canonical_json(body),
            )
        except Exception as exc:
            raise WorkspaceRevisionJobInDoubt(
                "protected wrapper transport failed after dispatch invocation"
            ) from exc
        if result.returncode != 0:
            if result.timed_out or result.process_started:
                raise WorkspaceRevisionJobInDoubt(
                    "protected wrapper may have accepted the exact dispatch"
                )
            raise WorkspaceRevisionJobNoEffect(
                "protected wrapper dispatch did not start"
            )
        try:
            response = self._parse_receipt(result.stdout, label="dispatch receipt")
            handle = self._validate_handle_response(spec, response)
        except (ValueError, WorkspaceRevisionJobError) as exc:
            raise WorkspaceRevisionJobInDoubt(
                "protected wrapper response did not prove the dispatch outcome"
            ) from exc
        with self._lock:
            self._write_once(handle_path, handle)
        return handle

    def reconcile(self, spec: ExecutorWorkspaceRunSpec) -> dict[str, Any]:
        qualification = self._qualification(
            target_profile_digest=spec.target_profile_digest,
            runner_policy_digest=spec.runner_policy_digest,
            toolchain_digest=spec.toolchain_digest,
        )
        self._require_dispatch_intent(spec)
        response = self._invoke_wrapper(
            qualification,
            "reconcile",
            {"runspec": spec.to_dict()},
            stage="workspace_job_reconcile",
        )
        disposition = response.get("disposition")
        if disposition == "accepted":
            handle = self._validate_handle_response(spec, response)
            with self._lock:
                self._write_once(self._record_path("handles", spec.dispatch_id), handle)
            return handle
        fields = {
            "schema_version",
            "disposition",
            "safe_error_code",
            "reconciliation_receipt_digest",
        }
        if (
            disposition not in {"unknown", "conflict"}
            or set(response) != fields
            or response["schema_version"] != "workspace_job_reconciliation@1"
            or _DIGEST.fullmatch(
                str(response["reconciliation_receipt_digest"])
            )
            is None
        ):
            raise WorkspaceRevisionJobError("reconcile disposition is invalid")
        return response

    def reconcile_run(self, runner_run_id: str) -> dict[str, Any]:
        return self.reconcile(self._load_runspec(runner_run_id))

    def observe(self, spec: ExecutorWorkspaceRunSpec, *, index: int) -> dict[str, Any]:
        if index < 1:
            raise ValueError("observation index must be positive")
        qualification = self._qualification(
            target_profile_digest=spec.target_profile_digest,
            runner_policy_digest=spec.runner_policy_digest,
            toolchain_digest=spec.toolchain_digest,
        )
        handle = self._require_handle(spec)
        response = self._invoke_wrapper(
            qualification,
            "observe",
            {"runspec": spec.to_dict(), "handle": handle, "observation_index": index},
            stage="workspace_job_observe",
        )
        observation = self._validate_observation(spec, handle, index, response)
        with self._lock:
            self._write_once(
                self._record_path("observations", f"{spec.dispatch_id}-{index}"),
                observation,
            )
        return observation

    def observe_run(self, runner_run_id: str, *, index: int) -> dict[str, Any]:
        return self.observe(self._load_runspec(runner_run_id), index=index)

    def cancel(
        self,
        spec: ExecutorWorkspaceRunSpec,
        *,
        cancellation: dict[str, Any],
    ) -> dict[str, Any]:
        qualification = self._qualification(
            target_profile_digest=spec.target_profile_digest,
            runner_policy_digest=spec.runner_policy_digest,
            toolchain_digest=spec.toolchain_digest,
        )
        handle = self._require_handle(spec)
        self._validate_cancellation(handle=handle, cancellation=cancellation)
        response = self._invoke_wrapper(
            qualification,
            "cancel",
            {"runspec": spec.to_dict(), "handle": handle, "cancellation": cancellation},
            stage="workspace_job_cancel",
        )
        fields = frozenset(
            {
                "schema_version",
                "cancellation_id",
                "handle_id",
                "cancellation_requested",
                "terminal_settlement_proven",
                "backend_receipt_digest",
                "created_at",
                "receipt_digest",
            }
        )
        receipt = _require_exact_object(response, fields=fields, label="cancel receipt")
        if (
            receipt["schema_version"] != "workspace_job_cancellation_receipt@1"
            or receipt["cancellation_id"] != cancellation["cancellation_id"]
            or receipt["handle_id"] != handle["handle_id"]
            or receipt["cancellation_requested"] is not True
            or receipt["terminal_settlement_proven"] is not False
            or receipt["receipt_digest"]
            != _digest({key: value for key, value in receipt.items() if key != "receipt_digest"})
        ):
            raise WorkspaceRevisionJobError("cancel receipt identity mismatch")
        with self._lock:
            self._write_once(
                self._record_path("cancellations", str(receipt["cancellation_id"])),
                receipt,
            )
        return receipt

    def cancel_run(
        self,
        runner_run_id: str,
        *,
        cancellation: dict[str, Any],
    ) -> dict[str, Any]:
        return self.cancel(
            self._load_runspec(runner_run_id),
            cancellation=cancellation,
        )

    def _load_runspec(self, runner_run_id: str) -> ExecutorWorkspaceRunSpec:
        if _IDENTIFIER.fullmatch(runner_run_id) is None:
            raise ValueError("workspace runner run id is invalid")
        value = self._read_json(self._record_path("runspecs", runner_run_id))
        spec = ExecutorWorkspaceRunSpec.from_dict(value)
        if spec.runner_run_id != runner_run_id:
            raise WorkspaceRevisionJobError("runner run id index crossed RunSpec identity")
        self._require_dispatch_intent(spec)
        return spec

    @staticmethod
    def _validate_cancellation(
        *,
        handle: dict[str, Any],
        cancellation: dict[str, Any],
    ) -> None:
        fields = frozenset(
            {
                "schema_version",
                "cancellation_id",
                "execution_id",
                "handle_id",
                "execution_state_version",
                "execution_fencing_token",
                "idempotency_key",
                "reason_digest",
                "created_at",
            }
        )
        value = _require_exact_object(
            cancellation,
            fields=fields,
            label="cancellation intent",
        )
        if (
            value["schema_version"] != "workspace_job_cancellation_intent@1"
            or value["execution_id"] != handle["execution_id"]
            or value["handle_id"] != handle["handle_id"]
            or _IDENTIFIER.fullmatch(str(value["cancellation_id"])) is None
            or _DIGEST.fullmatch(str(value["reason_digest"])) is None
        ):
            raise WorkspaceRevisionJobError("cancellation intent identity mismatch")

    @staticmethod
    def _require_before_deadline(absolute_deadline: str) -> None:
        deadline = datetime.fromisoformat(absolute_deadline)
        if deadline.tzinfo is None or datetime.now(tz=UTC) >= deadline:
            raise WorkspaceRevisionJobError(
                "workspace job absolute deadline elapsed before external effect"
            )

    def _qualification(
        self,
        *,
        target_profile_digest: str,
        runner_policy_digest: str | None,
        toolchain_digest: str,
    ) -> WorkspaceJobRunnerQualification:
        if _DIGEST.fullmatch(target_profile_digest) is None:
            raise WorkspaceRevisionJobError("target qualification identity is invalid")
        path = (
            self.config.control_root
            / "workspace-job-qualifications"
            / (target_profile_digest.removeprefix("sha256:") + ".json")
        )
        data = self._read_json(path, require_private_owner=True)
        qualification = WorkspaceJobRunnerQualification.from_dict(data)
        if (
            qualification.target_profile_digest != target_profile_digest
            or qualification.toolchain_digest != toolchain_digest
            or (
                runner_policy_digest is not None
                and qualification.runner_policy_digest != runner_policy_digest
            )
        ):
            raise WorkspaceRevisionJobError("target qualification identity drifted")
        return qualification

    def _invoke_wrapper(
        self,
        qualification: WorkspaceJobRunnerQualification,
        action: str,
        body: dict[str, object],
        *,
        stage: str,
    ) -> dict[str, Any]:
        result = self.transport.run_ssh(
            [qualification.protected_wrapper_path, action, "--stdin-json"],
            check=False,
            timeout=self.config.execution.remote_execution_timeout_seconds,
            stage=stage,
            input_text=_canonical_json(body),
        )
        if result.returncode != 0:
            raise WorkspaceRevisionJobError(f"protected wrapper {action} failed")
        return self._parse_receipt(result.stdout, label=f"{action} receipt")

    @staticmethod
    def _dispatch_identity(spec: ExecutorWorkspaceRunSpec) -> dict[str, object]:
        return {
            "schema_version": "workspace_job_runner_dispatch_intent@1",
            "execution_id": spec.execution_id,
            "operation_id": spec.operation_id,
            "dispatch_id": spec.dispatch_id,
            "runner_run_id": spec.runner_run_id,
            "workspace_id": spec.executor_hpc_workspace_id,
            "workspace_generation": spec.executor_hpc_workspace_generation,
            "source_manifest_digest": spec.source_manifest_digest,
            "selected_mode": spec.selected_mode,
            "scheduler_marker": spec.scheduler_marker,
            "payload_digest": spec.payload_digest,
            "absolute_deadline": spec.absolute_deadline,
        }

    @staticmethod
    def _validate_scheduler_credential(
        *,
        spec: ExecutorWorkspaceRunSpec,
        qualification: WorkspaceJobRunnerQualification,
        credential: SchedulerOccurrenceCredential,
    ) -> None:
        if (
            credential.dispatch_id != spec.dispatch_id
            or credential.execution_id != spec.execution_id
            or credential.target_profile_digest != spec.target_profile_digest
            or credential.scheduler_marker != spec.scheduler_marker
            or credential.payload_digest != spec.payload_digest
            or credential.protected_wrapper_audience
            != qualification.scheduler_credential_audience
        ):
            raise WorkspaceRevisionJobError(
                "scheduler credential identity drifted from the dispatch occurrence"
            )

    def _require_dispatch_intent(self, spec: ExecutorWorkspaceRunSpec) -> None:
        expected = self._dispatch_identity(spec)
        actual = self._read_json(self._record_path("dispatch-intents", spec.dispatch_id))
        if actual != expected:
            raise WorkspaceRevisionJobError("dispatch ledger identity conflicts")

    def _require_handle(self, spec: ExecutorWorkspaceRunSpec) -> dict[str, Any]:
        self._require_dispatch_intent(spec)
        handle = self._read_json(self._record_path("handles", spec.dispatch_id))
        return self._validate_handle_response(spec, handle)

    @staticmethod
    def _validate_manifest_response(
        request: WorkspaceRevisionSourcePrepareRequest,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        fields = frozenset(
            {
                "schema_version",
                "manifest_id",
                "request_id",
                "workspace_id",
                "source_commit",
                "source_tree",
                "lfs_closure_manifest_digest",
                "binding_digest",
                "repository_policy_digest",
                "toolchain_digest",
                "owner_identity_digest",
                "entries",
                "created_at",
                "manifest_digest",
            }
        )
        manifest = _require_exact_object(response, fields=fields, label="source manifest")
        if (
            manifest["schema_version"] != "compute_source_manifest@1"
            or manifest["request_id"] != request.request_id
            or manifest["workspace_id"] != request.workspace_id
            or manifest["source_commit"] != request.source_commit
            or manifest["source_tree"] != request.source_tree
            or manifest["lfs_closure_manifest_digest"]
            != request.lfs_closure_manifest_digest
            or manifest["binding_digest"] != request.repository_binding_digest
            or manifest["repository_policy_digest"]
            != request.repository_policy_digest
            or manifest["toolchain_digest"] != request.toolchain_digest
            or manifest["owner_identity_digest"] != request.owner_identity_digest
            or manifest["manifest_digest"]
            != _digest({key: value for key, value in manifest.items() if key != "manifest_digest"})
        ):
            raise WorkspaceRevisionJobError("source manifest identity mismatch")
        entries = manifest["entries"]
        if not isinstance(entries, list) or not entries:
            raise WorkspaceRevisionJobError("source manifest entries are missing")
        paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
        if len(paths) != len(entries) or paths != sorted(set(paths)):
            raise WorkspaceRevisionJobError("source manifest entries are not canonical")
        if any(path == ".git" or str(path).startswith(".git/") for path in paths):
            raise WorkspaceRevisionJobError("Git metadata reached the compute manifest")
        return manifest

    @staticmethod
    def _validate_handle_response(
        spec: ExecutorWorkspaceRunSpec,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        fields = frozenset(
            {
                "schema_version",
                "disposition",
                "handle_id",
                "execution_id",
                "operation_id",
                "dispatch_id",
                "runner_run_id",
                "job_root_token",
                "target_profile_digest",
                "workspace_id",
                "remote_workspace_generation",
                "source_commit",
                "source_manifest_digest",
                "backend",
                "raw_handle_ciphertext",
                "acceptance_receipt_digest",
                "accepted_at",
                "credential_consumed_at",
                "credential_consumption_receipt_digest",
                "handle_digest",
            }
        )
        handle = _require_exact_object(response, fields=fields, label="external handle")
        if (
            handle["schema_version"] != "workspace_job_runner_handle@1"
            or handle["disposition"] != "accepted"
            or handle["execution_id"] != spec.execution_id
            or handle["operation_id"] != spec.operation_id
            or handle["dispatch_id"] != spec.dispatch_id
            or handle["runner_run_id"] != spec.runner_run_id
            or handle["target_profile_digest"] != spec.target_profile_digest
            or handle["workspace_id"] != spec.executor_hpc_workspace_id
            or handle["remote_workspace_generation"]
            != spec.executor_hpc_workspace_generation
            or handle["source_commit"] != spec.source_commit
            or handle["source_manifest_digest"] != spec.source_manifest_digest
            or handle["backend"]
            != ("slurm" if spec.selected_mode == "sbatch" else "direct")
            or handle["handle_digest"]
            != _digest({key: value for key, value in handle.items() if key != "handle_digest"})
        ):
            raise WorkspaceRevisionJobError("external handle identity mismatch")
        if spec.selected_mode == "sbatch" and (
            handle["credential_consumed_at"] is None
            or handle["credential_consumption_receipt_digest"] is None
        ):
            raise WorkspaceRevisionJobError(
                "Slurm handle lacks atomic credential consumption proof"
            )
        return handle

    @staticmethod
    def _validate_observation(
        spec: ExecutorWorkspaceRunSpec,
        handle: dict[str, Any],
        index: int,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        fields = frozenset(
            {
                "schema_version",
                "observation_id",
                "handle_id",
                "execution_id",
                "dispatch_id",
                "observation_index",
                "state",
                "exit_code",
                "terminal_receipt_digest",
                "bounded_stdout",
                "bounded_stderr",
                "observed_at",
                "observation_digest",
            }
        )
        observation = _require_exact_object(response, fields=fields, label="job observation")
        terminal = observation["state"] in {"succeeded", "failed", "cancelled"}
        if (
            observation["schema_version"] != "external_job_observation@1"
            or observation["observation_id"]
            != f"job_observation_{handle['handle_id']}_{index}"
            or observation["handle_id"] != handle["handle_id"]
            or observation["execution_id"] != spec.execution_id
            or observation["dispatch_id"] != spec.dispatch_id
            or observation["observation_index"] != index
            or terminal != (observation["terminal_receipt_digest"] is not None)
            or observation["observation_digest"]
            != _digest(
                {
                    key: value
                    for key, value in observation.items()
                    if key != "observation_digest"
                }
            )
        ):
            raise WorkspaceRevisionJobError("external observation identity mismatch")
        return observation

    @staticmethod
    def _parse_receipt(raw: str, *, label: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WorkspaceRevisionJobError(f"{label} is not JSON") from exc
        if not isinstance(value, dict):
            raise WorkspaceRevisionJobError(f"{label} must be an object")
        return value

    def _record_path(self, kind: str, identity: str) -> Path:
        if _IDENTIFIER.fullmatch(identity) is None:
            raise ValueError("workspace job ledger identity is invalid")
        return self._root / kind / f"{identity}.json"

    @staticmethod
    def _read_json(
        path: Path,
        *,
        require_private_owner: bool = False,
    ) -> dict[str, Any]:
        try:
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
                raise WorkspaceRevisionJobError(
                    "workspace job ledger record is not a regular file"
                )
            if require_private_owner and (
                metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077
            ):
                raise WorkspaceRevisionJobError(
                    "runner qualification is not private to the runner identity"
                )
            raw = path.read_text(encoding="utf-8")
            value = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceRevisionJobError(
                "required workspace job ledger record is unavailable"
            ) from exc
        if not isinstance(value, dict):
            raise WorkspaceRevisionJobError("workspace job ledger record is invalid")
        return value

    def _read_optional(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        return self._read_json(path)

    @staticmethod
    def _write_once(path: Path, value: dict[str, Any]) -> None:
        encoded = (_canonical_json(value) + "\n").encode("utf-8")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent_metadata = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or path.parent.is_symlink()
            or parent_metadata.st_uid != os.geteuid()
            or parent_metadata.st_mode & 0o077
        ):
            raise WorkspaceRevisionJobError(
                "workspace job ledger directory is not private to the runner identity"
            )
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                stat.S_IRUSR | stat.S_IWUSR,
            )
        except FileExistsError:
            existing = WorkspaceRevisionJobService._read_json(path)
            if existing != value:
                raise WorkspaceRevisionJobError(
                    "workspace job ledger identity conflicts"
                )
            return
        try:
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("short workspace job ledger write")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)


__all__ = [
    "SchedulerOccurrenceCredential",
    "WorkspaceJobRunnerQualification",
    "WorkspaceRevisionJobError",
    "WorkspaceRevisionJobInDoubt",
    "WorkspaceRevisionJobNoEffect",
    "WorkspaceRevisionJobService",
    "WorkspaceRevisionSourcePrepareRequest",
]
