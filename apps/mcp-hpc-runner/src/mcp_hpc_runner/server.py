from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import threading
from typing import Any
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlsplit
import uuid

from .attempts import RunnerAttemptJournal
from .attempts import RunnerAttemptPhase
from .attempts import RunnerAttemptState
from .attempts import RunnerEffectCertainty
from .attempts import RunnerRetryEligibility
from .attempts import runner_phase_precedes
from .config import RunnerConfig, load_config
from .contract_manifest import ToolContract, load_contract_manifest
from .errors import FailureMapper
from .mode import select_execution_mode
from .models import JobHandle, RunSpec
from .remote import CommandRunner
from .slurm import SlurmRunner
from .ssh_runner import SSHRunner
from .staging import StagingManager
from .store import ArtifactStore
from .transport import SshTransportManager
from .validation import ensure_valid_runspec
from .validation import safe_relative_path


_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PUBLIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RUNNER_EXECUTION_RESERVATION_SCHEMA_VERSION = "runner_execution_reservation@1"
_RUNNER_EXECUTION_RESERVATION_IDENTITY_SCHEMA_VERSION = (
    "runner_execution_reservation_identity@1"
)
_RUNNER_EXECUTION_RESERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "execution_id",
        "operation_id",
        "operation_digest",
        "approval_digest",
        "route_policy_id",
        "adapter_policy_id",
        "request_digest",
        "execution_mode",
    }
)
_PUBLIC_RUN_STATUSES = {
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
}
_FORBIDDEN_CALLER_TRANSPORT_KEYS = frozenset(
    {
        "ssh_host",
        "ssh_user",
        "ssh_target",
        "ssh_options",
        "identity_file",
        "private_key",
        "credential",
        "credentials",
        "credential_policy_id",
        "host_key_policy_id",
        "control_path",
        "controlpath",
        "control_master",
        "controlmaster",
        "control_persist",
        "controlpersist",
        "transport",
        "transport_policy",
        "transport_mode",
        "max_channels_per_target",
        "connect_attempts",
        "pre_effect_recovery_attempts",
        "retry_budget",
        "backoff_initial_seconds",
        "backoff_multiplier",
        "backoff_max_seconds",
        "health_check_interval_seconds",
        "health_check_timeout_seconds",
        "channel_acquire_timeout_seconds",
    }
)


def _reject_caller_transport_overrides(value: object, *, path: str = "runspec") -> None:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key).strip().casefold().replace("-", "_")
            item_path = f"{path}.{raw_key}"
            if key in _FORBIDDEN_CALLER_TRANSPORT_KEYS:
                raise ValueError(
                    "runner-owned SSH transport field cannot be supplied: "
                    + item_path
                )
            _reject_caller_transport_overrides(item, path=item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_caller_transport_overrides(item, path=f"{path}[{index}]")


class MCPHpcServer:
    def __init__(self, config_path: str | Path | None) -> None:
        self.config: RunnerConfig = load_config(config_path)
        self.store = ArtifactStore(self.config.artifact_root)
        self.command_runner = CommandRunner()
        self.transport_manager = SshTransportManager(
            self.config,
            self.command_runner,
        )
        self.attempt_journal = RunnerAttemptJournal(
            self.store,
            self.config,
            self.transport_manager,
        )
        self.attempt_recovery_report = (
            self.attempt_journal.recover_interrupted_attempts()
        )
        self.failure_mapper = FailureMapper()
        self._tool_contracts_by_adapter = {
            contract.adapter_id: contract for contract in load_contract_manifest()
        }
        self._reservation_locks_guard = threading.Lock()
        self._reservation_locks: dict[str, threading.Lock] = {}
        self.staging = StagingManager(
            self.config,
            self.store,
            self.command_runner,
            transport_manager=self.transport_manager,
        )
        self.ssh_runner = SSHRunner(
            self.config,
            self.store,
            self.staging,
            self.command_runner,
            self.failure_mapper,
            transport_manager=self.transport_manager,
            attempt_journal=self.attempt_journal,
        )
        self.slurm_runner = SlurmRunner(
            self.config,
            self.store,
            self.staging,
            self.command_runner,
            self.failure_mapper,
            transport_manager=self.transport_manager,
            attempt_journal=self.attempt_journal,
        )

    def close(self) -> dict[str, object]:
        ambiguous_runs = self.attempt_journal.record_shutdown_ambiguities()
        report = self.transport_manager.shutdown()
        return {
            **report,
            "ambiguous_direct_run_count": len(ambiguous_runs),
        }

    def _tools(self) -> list[dict[str, Any]]:
        opaque_run_id_schema = {
            "type": "object",
            "required": ["run_id"],
            "additionalProperties": False,
            "properties": {"run_id": {"type": "string"}},
        }
        public_runspec_schema = {
            "type": "object",
            "not": {"required": ["run_id"]},
        }
        return [
            {
                "name": "exec.run",
                "description": "Execute a RunSpec using ssh|sbatch|auto selection",
                "inputSchema": {
                    "type": "object",
                    "required": ["runspec"],
                    "additionalProperties": False,
                    "properties": {
                        "runspec": public_runspec_schema,
                        "mode_override": {
                            "type": "string",
                            "enum": ["ssh", "sbatch", "auto"],
                        },
                    },
                },
            },
            {
                "name": "job.submit",
                "description": "Submit a RunSpec as an sbatch job",
                "inputSchema": {
                    "type": "object",
                    "required": ["runspec"],
                    "additionalProperties": False,
                    "properties": {"runspec": public_runspec_schema},
                },
            },
            {
                "name": "job.status",
                "description": "Query status by opaque server-issued run_id",
                "inputSchema": opaque_run_id_schema,
            },
            {
                "name": "job.logs",
                "description": "Fetch remote slurm log tails",
                "inputSchema": {
                    "type": "object",
                    "required": ["run_id"],
                    "additionalProperties": False,
                    "properties": {
                        "run_id": {"type": "string"},
                        "tail_lines": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": self.config.limits.max_tail_lines,
                            "default": 200,
                        },
                    },
                },
            },
            {
                "name": "job.cancel",
                "description": "Cancel a submitted Slurm job by opaque run_id",
                "inputSchema": opaque_run_id_schema,
            },
            {
                "name": "job.fetch_artifacts",
                "description": (
                    "Download persisted declared outputs by opaque run_id and "
                    "validate success checks"
                ),
                "inputSchema": opaque_run_id_schema,
            },
        ]

    @staticmethod
    def _require_arguments(
        tool_name: str,
        args: dict[str, Any],
        *,
        required: frozenset[str],
        allowed: frozenset[str],
    ) -> None:
        unexpected = sorted(set(args) - allowed)
        if unexpected:
            raise ValueError(
                f"{tool_name} received unexpected arguments: {', '.join(unexpected)}"
            )
        missing = sorted(required - set(args))
        if missing:
            raise ValueError(
                f"{tool_name} is missing required arguments: {', '.join(missing)}"
            )

    def _new_run_id(self) -> str:
        for _ in range(10):
            # The value is an opaque authority handle, not a display id. Keep
            # the full UUID entropy so guessing it is not a realistic access
            # path even inside the trusted Host boundary.
            run_id = uuid.uuid4().hex
            if not self.store.run_root(run_id).exists():
                return run_id
        raise RuntimeError("Unable to allocate a unique runner run_id")

    @staticmethod
    def _canonical_digest(value: object) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _validated_reservation_identity(
        cls,
        raw: dict[str, Any],
    ) -> dict[str, object]:
        if not isinstance(raw, dict):
            raise ValueError("runner execution reservation identity must be an object")
        if set(raw) != _RUNNER_EXECUTION_RESERVATION_FIELDS:
            raise ValueError(
                "runner execution reservation identity fields are incomplete or unknown"
            )
        if (
            raw.get("schema_version")
            != _RUNNER_EXECUTION_RESERVATION_IDENTITY_SCHEMA_VERSION
        ):
            raise ValueError("runner execution reservation identity schema is unsupported")
        identifiers = {
            key: str(raw.get(key) or "")
            for key in (
                "execution_id",
                "operation_id",
                "route_policy_id",
                "adapter_policy_id",
            )
        }
        if any(
            _PUBLIC_ID_PATTERN.fullmatch(value) is None
            for value in identifiers.values()
        ):
            raise ValueError("runner execution reservation contains an invalid identity")
        digests = {
            key: str(raw.get(key) or "")
            for key in (
                "operation_digest",
                "approval_digest",
                "request_digest",
            )
        }
        if any(_DIGEST_PATTERN.fullmatch(value) is None for value in digests.values()):
            raise ValueError("runner execution reservation contains an invalid digest")
        execution_mode = str(raw.get("execution_mode") or "")
        if execution_mode not in {"ssh", "sbatch", "auto"}:
            raise ValueError("runner execution reservation mode is invalid")
        return {
            "schema_version": _RUNNER_EXECUTION_RESERVATION_IDENTITY_SCHEMA_VERSION,
            **identifiers,
            **digests,
            "execution_mode": execution_mode,
        }

    def reserve_execution(self, identity: dict[str, Any]) -> dict[str, str]:
        """Reserve one server-issued opaque run id without remote side effects."""

        normalized = self._validated_reservation_identity(identity)
        identity_digest = self._canonical_digest(normalized)
        identity_hex = identity_digest.removeprefix("sha256:")
        try:
            record = self.store.read_reservation(identity_hex)
        except FileNotFoundError:
            candidate = {
                "schema_version": _RUNNER_EXECUTION_RESERVATION_SCHEMA_VERSION,
                "identity": normalized,
                "identity_digest": identity_digest,
                "run_id": self._new_run_id(),
            }
            try:
                self.store.write_reservation_once(identity_hex, candidate)
                record = candidate
            except FileExistsError:
                record = self.store.read_reservation(identity_hex)
        if (
            record.get("schema_version")
            != _RUNNER_EXECUTION_RESERVATION_SCHEMA_VERSION
            or record.get("identity") != normalized
            or record.get("identity_digest") != identity_digest
            or _PUBLIC_ID_PATTERN.fullmatch(str(record.get("run_id") or "")) is None
        ):
            raise ValueError("runner execution reservation identity drift")
        run_id = str(record["run_id"])
        self.store.ensure_run_layout(run_id)
        try:
            self.store.write_json_once(
                run_id,
                "execution_reservation.json",
                dict(record),
            )
        except FileExistsError:
            if self.store.read_json(run_id, "execution_reservation.json") != record:
                raise ValueError("runner execution reservation record drift")
        return {
            "run_id": run_id,
            "identity_digest": identity_digest,
        }

    def _load_execution_reservation(self, run_id: str) -> dict[str, Any]:
        if _PUBLIC_ID_PATTERN.fullmatch(str(run_id)) is None:
            raise ValueError("runner execution reservation run id is invalid")
        record = self.store.read_json(run_id, "execution_reservation.json")
        identity = self._validated_reservation_identity(
            dict(record.get("identity") or {})
        )
        identity_digest = self._canonical_digest(identity)
        indexed = self.store.read_reservation(
            identity_digest.removeprefix("sha256:")
        )
        if (
            record.get("schema_version")
            != _RUNNER_EXECUTION_RESERVATION_SCHEMA_VERSION
            or record.get("identity_digest") != identity_digest
            or record.get("run_id") != run_id
            or indexed != record
        ):
            raise ValueError("runner execution reservation record is inconsistent")
        return record

    def _reserved_runspec(self, raw: Any, *, run_id: str) -> RunSpec:
        if not isinstance(raw, dict):
            raise ValueError("runspec must be an object")
        if "run_id" in raw:
            raise ValueError("RunSpec.run_id is server-generated and must not be supplied")
        _reject_caller_transport_overrides(raw)
        reservation = self._load_execution_reservation(run_id)
        identity = dict(reservation["identity"])
        spec = RunSpec.from_dict(raw)
        requested_mode = str(identity["execution_mode"])
        if requested_mode != "auto" and spec.execution_mode != requested_mode:
            raise ValueError("reserved runner execution mode drift")
        metadata = dict(spec.metadata or {})
        if "openzyme_durable_execution" in metadata:
            raise ValueError("runner-owned durable execution identity cannot be supplied")
        metadata["openzyme_durable_execution"] = {
            "execution_id": identity["execution_id"],
            "operation_id": identity["operation_id"],
            "operation_digest": identity["operation_digest"],
            "approval_digest": identity["approval_digest"],
            "route_policy_id": identity["route_policy_id"],
            "adapter_policy_id": identity["adapter_policy_id"],
            "request_digest": identity["request_digest"],
            "reservation_identity_digest": reservation["identity_digest"],
        }
        spec.metadata = metadata
        spec.run_id = run_id
        self._bind_runner_toolchain_contract(spec)
        ensure_valid_runspec(
            spec,
            limits=self.config.limits,
            allowed_partitions=self.config.slurm.allowed_partitions,
        )
        return spec

    def submit_reserved_execution(
        self,
        *,
        run_id: str,
        runspec: dict[str, Any],
        mode_override: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch one previously reserved run, refusing every replay."""

        with self._reservation_locks_guard:
            reservation_lock = self._reservation_locks.setdefault(
                str(run_id),
                threading.Lock(),
            )
        with reservation_lock:
            return self._submit_reserved_execution_locked(
                run_id=run_id,
                runspec=runspec,
                mode_override=mode_override,
            )

    def _submit_reserved_execution_locked(
        self,
        *,
        run_id: str,
        runspec: dict[str, Any],
        mode_override: str | None,
    ) -> dict[str, Any]:

        spec = self._reserved_runspec(runspec, run_id=run_id)
        selected = select_execution_mode(spec, self.config, mode_override)
        binding = {
            "schema_version": "runner_reserved_dispatch_binding@1",
            "run_id": run_id,
            "reservation_identity_digest": self._load_execution_reservation(run_id)[
                "identity_digest"
            ],
            "runspec_digest": self._canonical_digest(spec.to_dict()),
            "selected_mode": selected,
        }
        try:
            self.store.write_json_once(
                run_id,
                "reserved_dispatch_binding.json",
                binding,
            )
        except FileExistsError:
            if self.store.read_json(run_id, "reserved_dispatch_binding.json") != binding:
                raise ValueError("reserved runner dispatch binding drift")
        runspec_path = self.store.run_root(run_id) / "metadata" / "runspec.json"
        if runspec_path.exists():
            persisted_spec = RunSpec.from_dict(
                self.store.read_json(run_id, "runspec.json")
            )
            if persisted_spec.to_dict() != spec.to_dict():
                raise ValueError("reserved runner persisted RunSpec drift")
        else:
            self.store.write_json_once(run_id, "runspec.json", spec.to_dict())
        if self.attempt_journal.has_attempt(run_id):
            attempt = self.attempt_journal.load_bound(
                run_id,
                spec,
                selected_mode=selected,
            )
            if (
                attempt.state is RunnerAttemptState.ACTIVE
                and attempt.effect_certainty is RunnerEffectCertainty.NO_EFFECT
                and runner_phase_precedes(
                    attempt.phase,
                    RunnerAttemptPhase.DISPATCHING,
                )
            ):
                return self._resume_spec(spec, selected_mode=selected)
            raise ValueError("reserved runner execution already crossed dispatch")
        return self._dispatch_spec(spec, mode_override=mode_override)

    def _resume_spec(self, spec: RunSpec, *, selected_mode: str) -> dict[str, Any]:
        if selected_mode == "ssh":
            result = self.ssh_runner.resume_pre_effect(spec).to_dict()
        elif selected_mode == "sbatch":
            result = self.slurm_runner.resume_pre_effect(spec).to_dict()
        else:
            raise ValueError("reserved runner recovery mode is invalid")
        return self._project_run_result(
            result,
            authoritative_mode=selected_mode,
            runtime_request=dict(
                spec.metadata.get("toolchain_runtime_request") or {}
            )
            or None,
        )

    def _dispatch_spec(
        self,
        spec: RunSpec,
        *,
        mode_override: str | None,
    ) -> dict[str, Any]:
        selected = select_execution_mode(spec, self.config, mode_override)
        if selected == "ssh":
            result = self.ssh_runner.exec_run(spec).to_dict()
        else:
            result = self.slurm_runner.submit(spec).to_dict()
        return self._project_run_result(
            result,
            authoritative_mode=selected,
            runtime_request=dict(
                spec.metadata.get("toolchain_runtime_request") or {}
            )
            or None,
        )

    def inspect_reserved_execution(self, run_id: str) -> dict[str, Any]:
        """Return a closed, locator-free observation for one exact reservation."""

        reservation = self._load_execution_reservation(run_id)
        identity = dict(reservation["identity"])
        runspec_path = self.store.run_root(run_id) / "metadata" / "runspec.json"
        if not runspec_path.exists() and not self.attempt_journal.has_attempt(run_id):
            return {
                "run_id": run_id,
                "status": "reserved",
                "selected_mode": identity["execution_mode"],
                "phase": "allocated",
                "effect_certainty": "no_effect",
                "retry_eligibility": "same_phase_safe",
                "reconciliation_required": False,
                "retryable": True,
                "runner_attempt_receipt_digest": self._canonical_digest(
                    {
                        "run_id": run_id,
                        "identity_digest": reservation["identity_digest"],
                        "state": "reserved",
                    }
                ),
                "artifacts": {},
            }
        spec = self._load_runspec_for_run(run_id)
        selected_mode = (
            "sbatch"
            if (self.store.run_root(run_id) / "metadata" / "job_handle.json").exists()
            else select_execution_mode(spec, self.config, None)
        )
        if not self.attempt_journal.has_attempt(run_id):
            return {
                "run_id": run_id,
                "status": "reserved",
                "selected_mode": selected_mode,
                "phase": "allocated",
                "effect_certainty": "no_effect",
                "retry_eligibility": "same_phase_safe",
                "reconciliation_required": False,
                "retryable": True,
                "runner_attempt_receipt_digest": self._canonical_digest(
                    {
                        "run_id": run_id,
                        "runspec_digest": self._canonical_digest(spec.to_dict()),
                        "state": "runspec_persisted_before_attempt",
                    }
                ),
                "artifacts": {},
            }
        attempt = self.attempt_journal.load_bound(
            run_id,
            spec,
            selected_mode=selected_mode,
        )
        if selected_mode == "sbatch" and (
            self.store.run_root(run_id) / "metadata" / "job_handle.json"
        ).exists():
            status = self._project_job_status(
                self.slurm_runner.status(self._load_handle(run_id)).to_dict()
            )
            return {
                **status,
                "status": status.get("state"),
                "selected_mode": "sbatch",
                "artifacts": {},
            }
        try:
            metadata = self.store.read_json(run_id, "run_result_metadata.json")
        except FileNotFoundError:
            metadata = {}
        if attempt.state is RunnerAttemptState.TERMINAL and metadata:
            status = str(metadata.get("status") or "failed")
            artifacts: dict[str, str] = {}
            if status == "completed":
                try:
                    output_manifest = self.store.read_json(
                        run_id,
                        "outputs_manifest.json",
                    )
                except FileNotFoundError:
                    output_manifest = {"entries": []}
                artifacts = {
                    str(item["remote_path"]): str(item["local_path"])
                    for item in list(output_manifest.get("entries") or [])
                    if int(item.get("returncode", 1)) == 0
                    and item.get("remote_path")
                    and item.get("local_path")
                }
            return self._project_run_result(
                {
                    "run_id": run_id,
                    "status": status,
                    "selected_mode": "ssh",
                    "exit_code": metadata.get("exit_code"),
                    "error_code": metadata.get("error_code"),
                    "artifacts": artifacts,
                    "logs": {},
                    "metadata": metadata,
                    "toolchain_runtime_identity": metadata.get(
                        "toolchain_runtime_identity"
                    ),
                },
                authoritative_mode="ssh",
                runtime_request=dict(
                    spec.metadata.get("toolchain_runtime_request") or {}
                )
                or None,
            )
        status = (
            "failed"
            if attempt.state
            in {
                RunnerAttemptState.RECONCILIATION_REQUIRED,
                RunnerAttemptState.QUARANTINED,
            }
            else "running"
        )
        return {
            "run_id": run_id,
            "status": status,
            "selected_mode": selected_mode,
            "phase": attempt.phase.value,
            "effect_certainty": attempt.effect_certainty.value,
            "retry_eligibility": attempt.retry_eligibility.value,
            "reconciliation_required": attempt.reconciliation_required,
            "retryable": attempt.retry_eligibility
            in {
                RunnerRetryEligibility.SAME_PHASE_SAFE,
                RunnerRetryEligibility.VERIFY_THEN_RETRY,
            },
            "runner_attempt_receipt_digest": attempt.safe_receipt_digest,
            "error_code": attempt.safe_failure_code,
            "artifacts": {},
        }

    def recover_reserved_execution_outcome(self, run_id: str) -> dict[str, Any]:
        """Resume result recovery for one exact run without replaying its payload."""

        self._load_execution_reservation(run_id)
        spec = self._load_runspec_for_run(run_id)
        selected_mode = (
            "sbatch"
            if (self.store.run_root(run_id) / "metadata" / "job_handle.json").exists()
            else select_execution_mode(spec, self.config, None)
        )
        self.attempt_journal.load_bound(
            run_id,
            spec,
            selected_mode=selected_mode,
        )
        if selected_mode == "ssh":
            result = self.ssh_runner.recover_terminal_outcome(spec).to_dict()
        elif selected_mode == "sbatch":
            result = self.slurm_runner.fetch_artifacts(
                spec,
                self._load_handle(run_id),
            ).to_dict()
        else:
            raise ValueError("reserved runner recovery mode is invalid")
        return self._project_run_result(
            result,
            authoritative_mode=selected_mode,
            runtime_request=dict(
                spec.metadata.get("toolchain_runtime_request") or {}
            )
            or None,
        )

    def _public_runspec(self, raw: Any) -> RunSpec:
        if not isinstance(raw, dict):
            raise ValueError("runspec must be an object")
        if "run_id" in raw:
            raise ValueError("RunSpec.run_id is server-generated and must not be supplied")
        _reject_caller_transport_overrides(raw)
        spec = RunSpec.from_dict(raw)
        spec.run_id = self._new_run_id()
        self._bind_runner_toolchain_contract(spec)
        ensure_valid_runspec(
            spec,
            limits=self.config.limits,
            allowed_partitions=self.config.slurm.allowed_partitions,
        )
        return spec

    def _bind_runner_toolchain_contract(self, spec: RunSpec) -> None:
        metadata = dict(spec.metadata or {})
        caller_owned_runtime_fields = sorted(
            {"toolchain_runtime_request", "toolchain_runtime_identity"} & set(metadata)
        )
        if caller_owned_runtime_fields:
            raise ValueError(
                "runner-owned toolchain runtime fields cannot be supplied: "
                + ", ".join(caller_owned_runtime_fields)
            )
        caller_contract = dict(metadata.get("tool_contract") or {})
        adapter_id = str(caller_contract.get("adapter_id") or "")
        contract = self._tool_contracts_by_adapter.get(adapter_id)
        if (
            contract is None
            or contract.entrypoint.get("kind") != "sif"
            or contract.command_template_id is None
        ):
            return
        self._validate_caller_tool_contract(caller_contract, contract)
        contract_digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    contract.raw,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        entrypoint = contract.entrypoint
        caller_contract.update(
            {
                "preflight_hints": {
                    "entrypoint": {
                        "kind": "sif",
                        "path": str(entrypoint["path"]),
                    },
                    "bind_paths": list(entrypoint.get("bind_paths") or []),
                },
                "runner_contract_digest": contract_digest,
            }
        )
        metadata["tool_contract"] = caller_contract
        metadata["toolchain_runtime_request"] = {
            "schema_id": "mcp_hpc_toolchain_runtime_request@1",
            "tool_id": contract.tool_id,
            "adapter_id": contract.adapter_id,
            "command_template_id": contract.command_template_id,
            "entrypoint_kind": "sif",
            "sif_locator": str(entrypoint["path"]),
            "runner_contract_digest": contract_digest,
        }
        spec.metadata = metadata

    @staticmethod
    def _validate_caller_tool_contract(
        caller: dict[str, Any],
        contract: ToolContract,
    ) -> None:
        if (
            caller.get("tool_id") != contract.tool_id
            or caller.get("adapter_id") != contract.adapter_id
            or not contract.command_template_id
            or caller.get("command_template_id") != contract.command_template_id
        ):
            raise ValueError(
                "Host tool contract does not match the runner-owned SIF contract"
            )

    def _load_handle(self, run_id: str) -> JobHandle:
        try:
            handle = self.slurm_runner.load_handle(run_id)
        except FileNotFoundError as exc:
            raise ValueError(
                f"No persisted job handle exists for run_id {run_id!r}"
            ) from exc
        if handle.run_id != run_id:
            raise ValueError(
                f"Persisted job handle does not belong to run_id {run_id!r}"
            )
        return handle

    def _load_runspec_for_run(self, run_id: str) -> RunSpec:
        try:
            spec = RunSpec.from_dict(self.store.read_json(run_id, "runspec.json"))
        except FileNotFoundError as exc:
            raise ValueError(
                f"No persisted RunSpec exists for run_id {run_id!r}"
            ) from exc
        if spec.run_id != run_id:
            raise ValueError(
                f"Persisted RunSpec does not belong to run_id {run_id!r}"
            )
        return spec

    def _validate_attempt_for_existing_run(
        self,
        run_id: str,
        *,
        spec: RunSpec | None = None,
    ) -> None:
        if not self.attempt_journal.has_attempt(run_id):
            if self.transport_manager.enabled:
                raise ValueError(
                    "persistent-transport run has no runner attempt journal"
                )
            return
        bound_spec = spec or self._load_runspec_for_run(run_id)
        self.attempt_journal.load_bound(
            run_id,
            bound_spec,
            selected_mode="sbatch",
        )

    @staticmethod
    def _relative_artifact_path(path: str) -> str:
        remote_path = PurePosixPath(path)
        parts = remote_path.parts
        if "out" in parts:
            out_index = len(parts) - 1 - list(reversed(parts)).index("out")
            remainder = parts[out_index + 1 :]
            if remainder:
                return str(PurePosixPath(*remainder))
        if not remote_path.is_absolute() and ".." not in parts:
            return remote_path.as_posix()
        return remote_path.name

    def _project_artifact_refs(
        self,
        run_id: str,
        artifacts: dict[str, object],
    ) -> dict[str, str]:
        projected: dict[str, str] = {}
        output_root = (self.store.run_root(run_id) / "outputs").resolve()
        for remote_path, storage_uri in artifacts.items():
            relative = self._relative_artifact_path(str(remote_path))
            safe_relative = safe_relative_path(
                relative,
                field="runner artifact relative path",
            )
            expected = (output_root / Path(*safe_relative.parts)).resolve()
            if expected != Path(str(storage_uri)).resolve():
                raise ValueError(
                    "runner artifact storage path does not match its run-scoped output"
                )
            if not expected.exists() or expected.is_symlink():
                raise ValueError("runner artifact output is missing or unsafe")
            projected[safe_relative.as_posix()] = (
                f"runner-artifact://{run_id}/"
                + quote(safe_relative.as_posix(), safe="/-._~")
            )
        return projected

    def resolve_artifact_ref(self, artifact_ref: str) -> str:
        """Resolve a runner artifact only inside the injected Host boundary."""

        parsed = urlsplit(str(artifact_ref))
        if parsed.scheme != "runner-artifact" or parsed.query or parsed.fragment:
            raise ValueError("runner artifact reference is invalid")
        run_id = parsed.netloc
        if _PUBLIC_ID_PATTERN.fullmatch(run_id) is None:
            raise ValueError("runner artifact reference has an invalid run id")
        relative = safe_relative_path(
            unquote(parsed.path.lstrip("/")),
            field="runner artifact reference path",
        )
        spec = self._load_runspec_for_run(run_id)
        declared = {
            safe_relative_path(item.path, field="expected_outputs.path").as_posix()
            for item in spec.expected_outputs
        }
        if relative.as_posix() not in declared:
            raise ValueError("runner artifact reference is not a declared output")
        if self.attempt_journal.has_attempt(run_id):
            selected_mode = (
                "sbatch"
                if (self.store.run_root(run_id) / "metadata" / "job_handle.json").exists()
                else "ssh"
            )
            attempt = self.attempt_journal.load_bound(
                run_id,
                spec,
                selected_mode=selected_mode,
            )
            if (
                attempt.state is not RunnerAttemptState.TERMINAL
                or attempt.phase is not RunnerAttemptPhase.TERMINAL
            ):
                raise ValueError("runner artifact attempt is not terminal")
        output_root = (self.store.run_root(run_id) / "outputs").resolve()
        target = (output_root / Path(*relative.parts)).resolve()
        if (
            target == output_root
            or output_root not in target.parents
            or not target.exists()
            or target.is_symlink()
        ):
            raise ValueError("runner artifact target is missing or unsafe")
        manifest = self.store.read_json(run_id, "outputs_manifest.json")
        manifest_paths = {
            self._relative_artifact_path(str(item.get("remote_path") or ""))
            for item in list(manifest.get("entries") or [])
            if int(item.get("returncode", 1)) == 0
        }
        if relative.as_posix() not in manifest_paths:
            raise ValueError("runner artifact is absent from the verified output manifest")
        return str(target)

    def _project_run_result(
        self,
        result: dict[str, Any],
        *,
        authoritative_mode: str,
        runtime_request: dict[str, object] | None,
    ) -> dict[str, Any]:
        reported_mode = str(result.get("selected_mode", "unknown"))
        if reported_mode != authoritative_mode:
            raise ValueError(
                "runner result selected_mode does not match the authoritative dispatch mode"
            )
        selected_mode = authoritative_mode
        raw_status = result.get("status")
        normalized_status = str(raw_status or "").strip().lower()
        status_valid = normalized_status in _PUBLIC_RUN_STATUSES
        status = normalized_status if status_valid else "failed"
        metadata = dict(result.get("metadata") or {})
        attempt_envelope = self._project_attempt_envelope(
            metadata,
            status=status,
            status_observation=False,
        )
        stage = metadata.get("stage")
        if selected_mode != "ssh" or stage != "remote_execution":
            stage = None
        projected = {
            "run_id": str(result["run_id"]),
            "status": status,
            "selected_mode": selected_mode,
            "exit_code": result.get("exit_code"),
            "error_code": result.get("error_code"),
            "stage": stage,
            "artifacts": {},
            # Raw runner logs remain Host-private. Async diagnostics are
            # retrieved separately through bounded operator-facing job.logs.
            "logs": {},
            **attempt_envelope,
        }
        if not status_valid and not projected["error_code"]:
            projected["error_code"] = "RUNNER_STATUS_INVALID"
        execution_identity = self._project_toolchain_runtime_identity(
            result,
            selected_mode=selected_mode,
            runtime_request=runtime_request,
        )
        if execution_identity is not None:
            projected["toolchain_runtime_identity"] = execution_identity
        elif (
            selected_mode == "ssh"
            and runtime_request
            and projected["status"] in {"completed", "succeeded", "success"}
        ):
            projected["status"] = "failed"
            projected["error_code"] = "TOOLCHAIN_IDENTITY_MISSING"
        if projected["status"] in {"completed", "succeeded", "success"}:
            projected["artifacts"] = self._project_artifact_refs(
                str(result["run_id"]),
                dict(result.get("artifacts") or {}),
            )
        return projected

    @staticmethod
    def _project_attempt_envelope(
        metadata: dict[str, Any],
        *,
        status: str,
        status_observation: bool = False,
    ) -> dict[str, object]:
        fields = {
            "runner_phase",
            "effect_certainty",
            "retry_eligibility",
            "reconciliation_required",
            "runner_attempt_safe_receipt_digest",
        }
        present = fields & set(metadata)
        if present:
            if present != fields:
                raise ValueError("runner attempt envelope is incomplete")
            try:
                phase = RunnerAttemptPhase(str(metadata["runner_phase"]))
                effect = RunnerEffectCertainty(str(metadata["effect_certainty"]))
                retry = RunnerRetryEligibility(str(metadata["retry_eligibility"]))
            except ValueError as exc:
                raise ValueError("runner attempt envelope contains an unknown value") from exc
            reconciliation = metadata["reconciliation_required"]
            receipt = str(metadata["runner_attempt_safe_receipt_digest"])
            if not isinstance(reconciliation, bool) or _DIGEST_PATTERN.fullmatch(
                receipt
            ) is None:
                raise ValueError("runner attempt envelope is invalid")
            if reconciliation != (
                effect is RunnerEffectCertainty.DISPATCH_IN_DOUBT
                and retry is RunnerRetryEligibility.RECONCILE_REQUIRED
            ):
                raise ValueError("runner attempt reconciliation facts are inconsistent")
            active_status = status in {
                "submitted",
                "queued",
                "pending",
                "running",
                "in_progress",
                "unknown",
            }
            success_status = status in {"completed", "succeeded", "success"}
            if active_status and (
                phase is not RunnerAttemptPhase.REMOTE_PENDING
                or effect is not RunnerEffectCertainty.EFFECT_KNOWN
                or retry is not RunnerRetryEligibility.VERIFY_THEN_RETRY
            ):
                raise ValueError("runner active attempt envelope is inconsistent")
            if success_status:
                if status_observation:
                    valid_success = (
                        phase is RunnerAttemptPhase.REMOTE_TERMINAL
                        and effect is RunnerEffectCertainty.TERMINAL_KNOWN
                        and retry
                        in {
                            RunnerRetryEligibility.VERIFY_THEN_RETRY,
                            RunnerRetryEligibility.TERMINAL,
                        }
                    )
                else:
                    valid_success = (
                        phase is RunnerAttemptPhase.TERMINAL
                        and effect is RunnerEffectCertainty.TERMINAL_KNOWN
                        and retry is RunnerRetryEligibility.TERMINAL
                    )
                if not valid_success:
                    raise ValueError("runner successful attempt envelope is inconsistent")
            if effect is RunnerEffectCertainty.DISPATCH_IN_DOUBT and (
                phase is not RunnerAttemptPhase.DISPATCHING
                or status != "failed"
            ):
                raise ValueError("runner ambiguous attempt envelope is inconsistent")
            if not status_observation and status in {
                "failed",
                "cancelled",
                "canceled",
            }:
                valid_failure = (
                    phase is RunnerAttemptPhase.TERMINAL
                    and retry is RunnerRetryEligibility.TERMINAL
                    and effect
                    in {
                        RunnerEffectCertainty.NO_EFFECT,
                        RunnerEffectCertainty.TERMINAL_KNOWN,
                    }
                ) or (
                    phase is RunnerAttemptPhase.DISPATCHING
                    and effect is RunnerEffectCertainty.DISPATCH_IN_DOUBT
                    and retry is RunnerRetryEligibility.RECONCILE_REQUIRED
                )
                if not valid_failure:
                    raise ValueError("runner failed attempt envelope is inconsistent")
        else:
            if status in {
                "submitted",
                "queued",
                "pending",
                "running",
                "in_progress",
                "unknown",
            }:
                phase = RunnerAttemptPhase.REMOTE_PENDING
                effect = RunnerEffectCertainty.EFFECT_KNOWN
                retry = RunnerRetryEligibility.VERIFY_THEN_RETRY
            else:
                phase = RunnerAttemptPhase.TERMINAL
                effect = (
                    RunnerEffectCertainty.TERMINAL_KNOWN
                    if status in {"completed", "succeeded", "success"}
                    else RunnerEffectCertainty.NO_EFFECT
                )
                retry = RunnerRetryEligibility.TERMINAL
            reconciliation = False
            receipt = None
        return {
            "phase": phase.value,
            "effect_certainty": effect.value,
            "retry_eligibility": retry.value,
            "reconciliation_required": reconciliation,
            "retryable": retry
            in {
                RunnerRetryEligibility.SAME_PHASE_SAFE,
                RunnerRetryEligibility.VERIFY_THEN_RETRY,
            },
            **(
                {}
                if receipt is None
                else {"runner_attempt_receipt_digest": receipt}
            ),
        }

    @staticmethod
    def _project_toolchain_runtime_identity(
        result: dict[str, Any],
        *,
        selected_mode: str,
        runtime_request: dict[str, object] | None,
    ) -> dict[str, str] | None:
        # Only the synchronous SSH runner can currently attest the image in the
        # same login shell that executes the payload. Never reinterpret Slurm
        # submit/preflight metadata as an execution identity.
        if selected_mode != "ssh" or not runtime_request:
            return None
        raw_identity = dict(
            dict(result.get("metadata") or {}).get("toolchain_runtime_identity") or {}
        )
        if not raw_identity:
            return None
        projected = {
            "schema_id": str(raw_identity.get("schema_id") or ""),
            "attestation_scope": str(raw_identity.get("attestation_scope") or ""),
            "execution_mode": str(raw_identity.get("execution_mode") or ""),
            "tool_id": str(raw_identity.get("tool_id") or ""),
            "adapter_id": str(raw_identity.get("adapter_id") or ""),
            "command_template_id": str(raw_identity.get("command_template_id") or ""),
            "runner_contract_digest": str(
                raw_identity.get("runner_contract_digest") or ""
            ),
            "image_digest": str(raw_identity.get("image_digest") or ""),
        }
        if (
            projected["schema_id"] != "mcp_hpc_toolchain_runtime_identity@1"
            or projected["attestation_scope"] != "same_ssh_login_shell_pre_exec"
            or projected["execution_mode"] != "ssh"
            or projected["tool_id"] != runtime_request.get("tool_id")
            or projected["adapter_id"] != runtime_request.get("adapter_id")
            or projected["command_template_id"]
            != runtime_request.get("command_template_id")
            or projected["runner_contract_digest"]
            != runtime_request.get("runner_contract_digest")
            or any(
                _PUBLIC_ID_PATTERN.fullmatch(projected[key]) is None
                for key in ("tool_id", "adapter_id", "command_template_id")
            )
            or _DIGEST_PATTERN.fullmatch(projected["runner_contract_digest"]) is None
            or _DIGEST_PATTERN.fullmatch(projected["image_digest"]) is None
        ):
            return None
        # Rebuild a closed public object instead of forwarding runner metadata;
        # paths and future private fields therefore cannot cross this boundary.
        return projected

    def _project_job_status(self, result: dict[str, Any]) -> dict[str, Any]:
        run_id = str(result["run_id"])
        state = str(result.get("state") or "unknown").strip().lower()
        attempt_metadata: dict[str, object] = {}
        if self.attempt_journal.has_attempt(run_id):
            attempt = self.attempt_journal.load(run_id)
            attempt_metadata = {
                "runner_attempt_safe_receipt_digest": attempt.safe_receipt_digest,
                "runner_phase": attempt.phase.value,
                "effect_certainty": attempt.effect_certainty.value,
                "retry_eligibility": attempt.retry_eligibility.value,
                "reconciliation_required": attempt.reconciliation_required,
            }
        projected = {
            key: result.get(key)
            for key in (
                "run_id",
                "state",
                "raw_state",
                "exit_code",
                "message",
                "started_at",
                "ended_at",
                "updated_at",
            )
        }
        projected.update(
            self._project_attempt_envelope(
                attempt_metadata,
                status=state,
                status_observation=True,
            )
        )
        return projected

    @staticmethod
    def _project_job_logs(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": str(result["run_id"]),
            "stdout": dict(result.get("stdout") or {}),
            "stderr": dict(result.get("stderr") or {}),
        }

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        args = arguments or {}
        if name == "exec.run":
            self._require_arguments(
                name,
                args,
                required=frozenset({"runspec"}),
                allowed=frozenset({"runspec", "mode_override"}),
            )
            spec = self._public_runspec(args["runspec"])
            return self._dispatch_spec(
                spec,
                mode_override=args.get("mode_override"),
            )

        if name == "job.submit":
            self._require_arguments(
                name,
                args,
                required=frozenset({"runspec"}),
                allowed=frozenset({"runspec"}),
            )
            spec = self._public_runspec(args["runspec"])
            spec.execution_mode = "sbatch"
            return self._project_run_result(
                self.slurm_runner.submit(spec).to_dict(),
                authoritative_mode="sbatch",
                runtime_request=None,
            )

        if name == "job.status":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id"}),
                allowed=frozenset({"run_id"}),
            )
            run_id = str(args["run_id"])
            handle = self._load_handle(run_id)
            self._validate_attempt_for_existing_run(run_id)
            return self._project_job_status(self.slurm_runner.status(handle).to_dict())

        if name == "job.logs":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id"}),
                allowed=frozenset({"run_id", "tail_lines"}),
            )
            run_id = str(args["run_id"])
            handle = self._load_handle(run_id)
            self._validate_attempt_for_existing_run(run_id)
            result = self.slurm_runner.logs(
                handle, tail_lines=int(args.get("tail_lines", 200))
            )
            return self._project_job_logs(result)

        if name == "job.cancel":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id"}),
                allowed=frozenset({"run_id"}),
            )
            run_id = str(args["run_id"])
            handle = self._load_handle(run_id)
            self._validate_attempt_for_existing_run(run_id)
            return self._project_run_result(
                self.slurm_runner.cancel(handle).to_dict(),
                authoritative_mode="sbatch",
                runtime_request=None,
            )

        if name == "job.fetch_artifacts":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id"}),
                allowed=frozenset({"run_id"}),
            )
            run_id = str(args["run_id"])
            handle = self._load_handle(run_id)
            spec = self._load_runspec_for_run(run_id)
            self._validate_attempt_for_existing_run(run_id, spec=spec)
            return self._project_run_result(
                self.slurm_runner.fetch_artifacts(spec, handle).to_dict(),
                authoritative_mode="sbatch",
                runtime_request=None,
            )

        raise ValueError(f"Unknown tool: {name}")

    def serve_stdio(self) -> None:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue

            request_id = None
            try:
                request = json.loads(raw)
                request_id = request.get("id") if isinstance(request, dict) else None
                response = self._handle_rpc(request)
            except Exception as exc:  # noqa: BLE001
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": str(exc)},
                }

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

    def _handle_rpc(self, request: dict[str, Any]) -> dict[str, Any]:
        rpc_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "serverInfo": {"name": "mcp-hpc-runner", "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"tools": self._tools()},
            }

        if method == "tools/call":
            tool_name = params["name"]
            tool_args = params.get("arguments", {})
            result = self.call_tool(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result)}],
                    "isError": False,
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
