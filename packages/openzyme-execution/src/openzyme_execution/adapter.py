from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Any
from typing import Protocol

from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_runtime.limits import LimiterRegistry
from openzyme_runtime.seams import ExecutionAdapter

_SUPPORTED_EXECUTION_TOOLS = frozenset({"exec.run"})
_TOOLCHAIN_RUNTIME_IDENTITY_FIELDS = (
    "schema_id",
    "attestation_scope",
    "execution_mode",
    "tool_id",
    "adapter_id",
    "command_template_id",
    "runner_contract_digest",
    "image_digest",
)
_SAFE_TOOLCHAIN_IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$"
)
_SHA256_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_RUNNER_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_RUNNER_ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_RUNNER_PHASES = frozenset(
    {
        "allocated",
        "transport_ready",
        "remote_layout_ready",
        "input_staging",
        "inputs_verified",
        "preflight_passed",
        "dispatch_prepared",
        "dispatching",
        "remote_pending",
        "remote_terminal",
        "outputs_fetching",
        "outputs_verified",
        "terminal",
    }
)
_RUNNER_EFFECT_CERTAINTIES = frozenset(
    {"no_effect", "dispatch_in_doubt", "effect_known", "terminal_known"}
)
_RUNNER_RETRY_ELIGIBILITIES = frozenset(
    {"same_phase_safe", "verify_then_retry", "reconcile_required", "terminal"}
)
_RUNNER_ENVELOPE_FIELDS = frozenset(
    {
        "phase",
        "effect_certainty",
        "retry_eligibility",
        "reconciliation_required",
        "retryable",
    }
)


class HpcRunnerToolServer(Protocol):
    def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def resolve_artifact_ref(self, artifact_ref: str) -> str: ...

    def reserve_execution(self, identity: dict[str, Any]) -> dict[str, str]: ...

    def submit_reserved_execution(
        self,
        *,
        run_id: str,
        runspec: dict[str, Any],
        mode_override: str | None = None,
    ) -> dict[str, Any]: ...

    def inspect_reserved_execution(self, run_id: str) -> dict[str, Any]: ...

    def recover_reserved_execution_outcome(self, run_id: str) -> dict[str, Any]: ...


def _artifact_kind_from_uri(storage_uri: str) -> ArtifactKind:
    path = storage_uri.lower()
    if path.endswith(".log") or "/logs/" in path:
        return ArtifactKind.LOG
    if path.endswith((".pdb", ".cif", ".mol2", ".sdf", ".pdbqt")):
        return ArtifactKind.STRUCTURE
    if path.endswith((".md", ".pdf", ".html")):
        return ArtifactKind.REPORT
    return ArtifactKind.RESULT


def _relative_output_path(remote_path: str) -> str:
    path = PurePosixPath(remote_path)
    parts = path.parts
    if "out" in parts:
        out_index = len(parts) - 1 - list(reversed(parts)).index("out")
        remainder = parts[out_index + 1 :]
        if remainder:
            return str(PurePosixPath(*remainder))
    if not path.is_absolute() and ".." not in parts:
        return path.as_posix()
    return path.name


def map_runner_status_to_run_status(status: str) -> RunStatus:
    normalized = status.lower()
    if normalized in {"submitted", "queued", "pending"}:
        return RunStatus.QUEUED
    if normalized in {"running", "in_progress"}:
        return RunStatus.RUNNING
    if normalized in {"completed", "succeeded", "success"}:
        return RunStatus.SUCCEEDED
    if normalized in {"cancelled", "canceled"}:
        return RunStatus.CANCELLED
    return RunStatus.FAILED


def _project_toolchain_runtime_identity(
    value: Any,
    *,
    execution_mode: str,
) -> dict[str, str] | None:
    if execution_mode != "ssh" or not isinstance(value, dict):
        return None
    identity = {
        field: str(value.get(field) or "")
        for field in _TOOLCHAIN_RUNTIME_IDENTITY_FIELDS
    }
    if (
        identity["schema_id"] != "mcp_hpc_toolchain_runtime_identity@1"
        or identity["attestation_scope"]
        != "same_ssh_login_shell_pre_exec"
        or identity["execution_mode"] != "ssh"
        or any(
            _SAFE_TOOLCHAIN_IDENTIFIER_PATTERN.fullmatch(identity[field]) is None
            for field in ("tool_id", "adapter_id", "command_template_id")
        )
        or any(
            _SHA256_DIGEST_PATTERN.fullmatch(identity[field]) is None
            for field in ("runner_contract_digest", "image_digest")
        )
    ):
        return None
    return identity


def _project_runner_attempt_envelope(
    result: dict[str, Any],
    *,
    status: RunStatus,
) -> dict[str, Any]:
    present = _RUNNER_ENVELOPE_FIELDS & set(result)
    if present and present != _RUNNER_ENVELOPE_FIELDS:
        raise ValueError("runner attempt envelope is incomplete")
    if not present:
        if status in {RunStatus.QUEUED, RunStatus.RUNNING}:
            phase = "remote_pending"
            effect_certainty = "effect_known"
            retry_eligibility = "verify_then_retry"
        else:
            phase = "terminal"
            effect_certainty = (
                "terminal_known"
                if status in {RunStatus.SUCCEEDED, RunStatus.CANCELLED}
                else "no_effect"
            )
            retry_eligibility = "terminal"
        reconciliation_required = False
        retryable = retry_eligibility == "verify_then_retry"
    else:
        phase = str(result["phase"])
        effect_certainty = str(result["effect_certainty"])
        retry_eligibility = str(result["retry_eligibility"])
        reconciliation_required = result["reconciliation_required"]
        retryable = result["retryable"]
        if (
            phase not in _RUNNER_PHASES
            or effect_certainty not in _RUNNER_EFFECT_CERTAINTIES
            or retry_eligibility not in _RUNNER_RETRY_ELIGIBILITIES
            or not isinstance(reconciliation_required, bool)
            or not isinstance(retryable, bool)
        ):
            raise ValueError("runner attempt envelope contains an unknown value")
        expected_reconciliation = (
            effect_certainty == "dispatch_in_doubt"
            and retry_eligibility == "reconcile_required"
        )
        expected_retryable = retry_eligibility in {
            "same_phase_safe",
            "verify_then_retry",
        }
        if (
            reconciliation_required != expected_reconciliation
            or retryable != expected_retryable
        ):
            raise ValueError("runner attempt envelope is internally inconsistent")
    receipt = result.get("runner_attempt_receipt_digest")
    if receipt is not None and (
        not isinstance(receipt, str)
        or _SHA256_DIGEST_PATTERN.fullmatch(receipt) is None
    ):
        raise ValueError("runner attempt receipt digest is invalid")
    return {
        "phase": phase,
        "effect_certainty": effect_certainty,
        "retry_eligibility": retry_eligibility,
        "reconciliation_required": reconciliation_required,
        "retryable": retryable,
        **(
            {}
            if receipt is None
            else {"runner_attempt_receipt_digest": receipt}
        ),
    }


@dataclass(frozen=True, slots=True)
class ExecutionArtifactRef:
    storage_uri: str
    relative_path: str
    kind: ArtifactKind


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    run_id: str
    status: RunStatus
    execution_mode: str
    artifacts: tuple[ExecutionArtifactRef, ...]
    raw_result: dict[str, Any]
    exit_code: int | None = None
    toolchain_runtime_identity: dict[str, str] | None = None
    phase: str = "terminal"
    effect_certainty: str = "no_effect"
    retry_eligibility: str = "terminal"
    reconciliation_required: bool = False
    retryable: bool = False
    runner_attempt_receipt_digest: str | None = None
    # Compatibility-only DTO fields. The active HPC adapter never populates raw
    # runner handles; it uses only an opaque URI and leaves job_id unset.
    remote_run_dir: str = ""
    job_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionStatusSnapshot:
    run_id: str
    status: RunStatus
    raw_result: dict[str, Any]
    exit_code: int | None = None
    phase: str = "remote_pending"
    effect_certainty: str = "effect_known"
    retry_eligibility: str = "verify_then_retry"
    reconciliation_required: bool = False
    retryable: bool = True
    runner_attempt_receipt_digest: str | None = None


@dataclass(frozen=True, slots=True)
class ReservedExecutionObservation:
    run_id: str
    status: str
    execution_mode: str
    phase: str
    effect_certainty: str
    retry_eligibility: str
    reconciliation_required: bool
    retryable: bool
    artifacts: tuple[ExecutionArtifactRef, ...] = ()
    exit_code: int | None = None
    error_code: str | None = None
    runner_attempt_receipt_digest: str | None = None


@dataclass(slots=True)
class HpcRunnerExecutionAdapter(ExecutionAdapter):
    config_path: str | None = None
    server: HpcRunnerToolServer | None = None
    limiter_registry: LimiterRegistry | None = None

    def __post_init__(self) -> None:
        if self.server is None:
            raise ValueError(
                "HpcRunnerExecutionAdapter requires an injected runner server. "
                "Instantiate mcp_hpc_runner.server.MCPHpcServer in the Host API composition root."
            )

    def submit_execution(self, session_id: str, payload: dict[str, Any]) -> ExecutionOutcome:
        requested_tool_name = str(payload.get("tool_name", "exec.run"))
        if requested_tool_name not in _SUPPORTED_EXECUTION_TOOLS:
            raise ValueError(
                f"unsupported execution tool {requested_tool_name!r}; expected 'exec.run'"
            )
        tool_name = requested_tool_name
        runspec = dict(payload["runspec"])
        if "run_id" in runspec:
            raise ValueError("RunSpec.run_id is server-generated and must not be supplied")
        metadata = dict(runspec.get("metadata", {}))
        metadata.setdefault("openzyme", {})
        metadata["openzyme"]["session_id"] = session_id
        runspec["metadata"] = metadata
        result = self._call_tool(tool_name, {"runspec": runspec})
        return self._normalize_result(result, declared_paths=_declared_output_paths(runspec))

    def reserve_execution(self, identity: dict[str, Any]) -> dict[str, str]:
        if self.server is None:
            raise RuntimeError("HPC runner server is not initialized")

        def operation() -> dict[str, str]:
            return self.server.reserve_execution(dict(identity))

        result = (
            operation()
            if self.limiter_registry is None
            else self.limiter_registry.sync_limiter("execution_provider").run(
                operation
            )
        )
        run_id = str(result.get("run_id") or "")
        identity_digest = str(result.get("identity_digest") or "")
        if (
            _SAFE_RUNNER_RUN_ID_PATTERN.fullmatch(run_id) is None
            or _SHA256_DIGEST_PATTERN.fullmatch(identity_digest) is None
        ):
            raise ValueError("runner returned an invalid execution reservation")
        return {"run_id": run_id, "identity_digest": identity_digest}

    def submit_reserved_execution(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        run_id: str,
    ) -> ExecutionOutcome:
        if self.server is None:
            raise RuntimeError("HPC runner server is not initialized")
        if _SAFE_RUNNER_RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValueError("reserved runner run id is invalid")
        requested_tool_name = str(payload.get("tool_name", "exec.run"))
        if requested_tool_name not in _SUPPORTED_EXECUTION_TOOLS:
            raise ValueError("reserved execution supports only exec.run")
        runspec = dict(payload["runspec"])
        if "run_id" in runspec:
            raise ValueError("RunSpec.run_id is server-generated and must not be supplied")
        metadata = dict(runspec.get("metadata", {}))
        metadata.setdefault("openzyme", {})
        metadata["openzyme"]["session_id"] = session_id
        runspec["metadata"] = metadata

        def operation() -> dict[str, Any]:
            return self.server.submit_reserved_execution(
                run_id=run_id,
                runspec=runspec,
            )

        result = (
            operation()
            if self.limiter_registry is None
            else self.limiter_registry.sync_limiter("execution_provider").run(
                operation
            )
        )
        if str(result.get("run_id") or "") != run_id:
            raise ValueError("reserved runner result identity drift")
        return self._normalize_result(
            result,
            declared_paths=_declared_output_paths(runspec),
        )

    def inspect_reserved_execution(
        self,
        *,
        run_id: str,
    ) -> ReservedExecutionObservation:
        if self.server is None:
            raise RuntimeError("HPC runner server is not initialized")
        if _SAFE_RUNNER_RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValueError("reserved runner run id is invalid")

        def operation() -> dict[str, Any]:
            return self.server.inspect_reserved_execution(run_id)

        result = (
            operation()
            if self.limiter_registry is None
            else self.limiter_registry.sync_limiter("execution_provider").run(
                operation
            )
        )
        return self._normalize_reserved_observation(result, run_id=run_id)

    def recover_reserved_execution_outcome(
        self,
        *,
        run_id: str,
    ) -> ExecutionOutcome:
        if self.server is None:
            raise RuntimeError("HPC runner server is not initialized")

        def operation() -> dict[str, Any]:
            return self.server.recover_reserved_execution_outcome(run_id)

        result = (
            operation()
            if self.limiter_registry is None
            else self.limiter_registry.sync_limiter("execution_provider").run(
                operation
            )
        )
        observation = self._normalize_reserved_observation(result, run_id=run_id)
        if observation.status in {
            "reserved",
            "submitted",
            "queued",
            "pending",
            "running",
            "in_progress",
        }:
            raise ValueError("reserved runner execution is not terminal")
        return self._normalize_result(result)

    def get_execution_status(
        self,
        *,
        run_id: str,
    ) -> ExecutionStatusSnapshot:
        result = self._call_tool(
            "job.status",
            {"run_id": run_id},
        )
        projected_run_id = str(result.get("run_id") or "")
        if (
            projected_run_id != run_id
            or _SAFE_RUNNER_RUN_ID_PATTERN.fullmatch(projected_run_id) is None
        ):
            raise ValueError("runner status identity does not match the requested run")
        status = map_runner_status_to_run_status(
            str(result.get("state", "failed"))
        )
        envelope = _project_runner_attempt_envelope(result, status=status)
        exit_code = result.get("exit_code")
        if exit_code is not None and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int)
        ):
            raise ValueError("runner status exit_code must be an integer or null")
        safe_result = {
            "run_id": projected_run_id,
            "state": str(result.get("state") or "failed"),
            "exit_code": exit_code,
            **envelope,
        }
        return ExecutionStatusSnapshot(
            run_id=projected_run_id,
            status=status,
            raw_result=safe_result,
            exit_code=exit_code,
            phase=str(envelope["phase"]),
            effect_certainty=str(envelope["effect_certainty"]),
            retry_eligibility=str(envelope["retry_eligibility"]),
            reconciliation_required=bool(envelope["reconciliation_required"]),
            retryable=bool(envelope["retryable"]),
            runner_attempt_receipt_digest=(
                None
                if envelope.get("runner_attempt_receipt_digest") is None
                else str(envelope["runner_attempt_receipt_digest"])
            ),
        )

    def fetch_execution_artifacts(
        self,
        *,
        run_id: str,
    ) -> ExecutionOutcome:
        result = self._call_tool(
            "job.fetch_artifacts",
            {"run_id": run_id},
        )
        return self._normalize_result(result)

    def cancel_execution(
        self,
        *,
        run_id: str,
    ) -> ExecutionOutcome:
        result = self._call_tool(
            "job.cancel",
            {"run_id": run_id},
        )
        return self._normalize_result(result)

    def _call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.server is None:
            raise RuntimeError("HPC runner server is not initialized")

        def operation() -> dict[str, Any]:
            return self.server.call_tool(tool_name, payload)

        if self.limiter_registry is None:
            return operation()
        return self.limiter_registry.sync_limiter("execution_provider").run(operation)

    def _normalize_result(
        self,
        result: dict[str, Any],
        *,
        declared_paths: set[str] | None = None,
    ) -> ExecutionOutcome:
        run_id = str(result.get("run_id") or "")
        if _SAFE_RUNNER_RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValueError("runner result contains an invalid opaque run id")
        selected_mode = str(
            result.get("selected_mode", result.get("requested_mode", "unknown"))
        )
        if selected_mode not in {"ssh", "sbatch"}:
            raise ValueError("runner result contains an invalid execution mode")
        run_status = map_runner_status_to_run_status(
            str(result.get("status", "failed"))
        )
        envelope = _project_runner_attempt_envelope(result, status=run_status)
        exit_code = result.get("exit_code")
        if exit_code is not None and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int)
        ):
            raise ValueError("runner result exit_code must be an integer or null")
        error_code = result.get("error_code")
        if error_code is not None and (
            not isinstance(error_code, str)
            or _SAFE_RUNNER_ERROR_CODE_PATTERN.fullmatch(error_code) is None
        ):
            raise ValueError("runner result error_code is invalid")
        stage = result.get("stage")
        if stage not in {None, "remote_execution"}:
            raise ValueError("runner result stage is invalid")
        toolchain_runtime_identity = _project_toolchain_runtime_identity(
            result.get("toolchain_runtime_identity"),
            execution_mode=selected_mode,
        )
        public_artifacts = dict(result.get("artifacts") or {})
        safe_result: dict[str, Any] = {
            "run_id": run_id,
            "status": str(result.get("status") or "failed"),
            "selected_mode": selected_mode,
            "exit_code": exit_code,
            "error_code": error_code,
            "stage": stage,
            "artifacts": public_artifacts,
            **envelope,
        }
        if toolchain_runtime_identity is None:
            safe_result.pop("toolchain_runtime_identity", None)
        else:
            safe_result["toolchain_runtime_identity"] = dict(
                toolchain_runtime_identity
            )
        if run_status is not RunStatus.SUCCEEDED:
            safe_result["artifacts"] = {}
        artifacts: list[ExecutionArtifactRef] = []
        for remote_path, artifact_ref in sorted(
            public_artifacts.items()
        ):
            relative_path = _relative_output_path(str(remote_path))
            if run_status is not RunStatus.SUCCEEDED or (
                declared_paths is not None and relative_path not in declared_paths
            ):
                continue
            storage_uri = str(artifact_ref)
            if not storage_uri.startswith("runner-artifact://"):
                raise ValueError("runner result exposed a non-opaque artifact reference")
            if self.server is None or not hasattr(
                self.server,
                "resolve_artifact_ref",
            ):
                raise ValueError(
                    "runner artifact reference requires the injected Host resolver"
                )
            storage_uri = self.server.resolve_artifact_ref(storage_uri)
            artifacts.append(
                ExecutionArtifactRef(
                    storage_uri=storage_uri,
                    relative_path=relative_path,
                    kind=_artifact_kind_from_uri(relative_path),
                )
            )
        return ExecutionOutcome(
            run_id=run_id,
            status=run_status,
            execution_mode=selected_mode,
            artifacts=tuple(artifacts),
            raw_result=safe_result,
            exit_code=exit_code,
            toolchain_runtime_identity=toolchain_runtime_identity,
            phase=str(envelope["phase"]),
            effect_certainty=str(envelope["effect_certainty"]),
            retry_eligibility=str(envelope["retry_eligibility"]),
            reconciliation_required=bool(envelope["reconciliation_required"]),
            retryable=bool(envelope["retryable"]),
            runner_attempt_receipt_digest=(
                None
                if envelope.get("runner_attempt_receipt_digest") is None
                else str(envelope["runner_attempt_receipt_digest"])
            ),
            remote_run_dir=f"opaque://{run_id}",
        )

    def _normalize_reserved_observation(
        self,
        result: dict[str, Any],
        *,
        run_id: str,
    ) -> ReservedExecutionObservation:
        if str(result.get("run_id") or "") != run_id:
            raise ValueError("reserved runner observation identity drift")
        status = str(result.get("status") or "")
        if status not in {
            "reserved",
            "submitted",
            "queued",
            "pending",
            "running",
            "in_progress",
            "completed",
            "succeeded",
            "success",
            "cancelled",
            "canceled",
            "failed",
        }:
            raise ValueError("reserved runner observation status is invalid")
        mode = str(result.get("selected_mode") or "")
        if mode not in {"ssh", "sbatch", "auto"}:
            raise ValueError("reserved runner observation mode is invalid")
        projected_status = (
            RunStatus.QUEUED
            if status == "reserved"
            else map_runner_status_to_run_status(status)
        )
        envelope = _project_runner_attempt_envelope(
            result,
            status=projected_status,
        )
        exit_code = result.get("exit_code")
        if exit_code is not None and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int)
        ):
            raise ValueError("reserved runner exit_code is invalid")
        error_code = result.get("error_code")
        if error_code is not None and (
            not isinstance(error_code, str)
            or _SAFE_RUNNER_ERROR_CODE_PATTERN.fullmatch(error_code) is None
        ):
            raise ValueError("reserved runner error_code is invalid")
        artifacts: tuple[ExecutionArtifactRef, ...] = ()
        if status in {"completed", "succeeded", "success"}:
            normalized = self._normalize_result(result)
            artifacts = normalized.artifacts
        return ReservedExecutionObservation(
            run_id=run_id,
            status=status,
            execution_mode=mode,
            phase=str(envelope["phase"]),
            effect_certainty=str(envelope["effect_certainty"]),
            retry_eligibility=str(envelope["retry_eligibility"]),
            reconciliation_required=bool(envelope["reconciliation_required"]),
            retryable=bool(envelope["retryable"]),
            artifacts=artifacts,
            exit_code=exit_code,
            error_code=error_code,
            runner_attempt_receipt_digest=(
                None
                if envelope.get("runner_attempt_receipt_digest") is None
                else str(envelope["runner_attempt_receipt_digest"])
            ),
        )


def _declared_output_paths(runspec: dict[str, Any]) -> set[str] | None:
    paths = {str(item.get("path")) for item in list(runspec.get("expected_outputs") or []) if item.get("path")}
    return paths or None
