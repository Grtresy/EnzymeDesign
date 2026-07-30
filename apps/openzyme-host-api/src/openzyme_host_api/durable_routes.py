from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
from typing import Any
from typing import NoReturn

from openzyme_core import ControlledOperationRouteAdapter
from openzyme_core import ControlledOperationResultArtifactRef
from openzyme_core import CoreRepositories
from openzyme_core import DURABLE_RESULT_ENVELOPE_MAX_BYTES
from openzyme_core import DurableRouteMaterializedResult
from openzyme_core import DurableRouteObservation
from openzyme_core import DurableRouteObservationKind
from openzyme_core import DurableExecutionHostAuthority
from openzyme_core import SandboxHostCallContext
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_core import is_transient_sqlite_contention
from openzyme_domain import ControlledOperationDispatchRequest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import RetryEligibility
from openzyme_domain import RunStatus
from openzyme_engines.execution import PipelineSdkFailure
from openzyme_runtime import S12_ROUTE_POLICIES
from openzyme_runtime import sanitize_public_diagnostic_payload

from .sandbox_host_gateway import ExecutionEngineSandboxHostGateway


_PROVIDER_ROUTE_IDS = frozenset(
    route_policy_id
    for route_policy_id, policy in S12_ROUTE_POLICIES.items()
    if policy.get("status") == "ok"
    and policy.get("selected_backend") == "provider_http"
)
_HPC_ROUTE_IDS = frozenset(
    route_policy_id
    for route_policy_id, policy in S12_ROUTE_POLICIES.items()
    if policy.get("status") == "ok" and policy.get("selected_backend") == "hpc"
)
_RUNNER_SUCCESS_STATUSES = frozenset({"completed", "succeeded", "success"})
_RUNNER_ACTIVE_STATUSES = frozenset(
    {"submitted", "queued", "pending", "running", "in_progress"}
)
_RUNNER_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "cancelled", "canceled"})
_PROVEN_PRE_EFFECT_PROVIDER_STAGES = frozenset(
    {
        "adapter_input_validation",
        "adapter_input_integrity",
        "adapter_context_validation",
        "provider_config_validation",
        "provider_route_policy_validation",
        "bio_input_validation",
    }
)
_S12_ADAPTER_ENVELOPE_SCHEMA = "s12.adapter_envelope.v1"
_PROVIDER_TRANSCRIPT_DOCUMENT_MAX_BYTES = 8 * 1024 * 1024
_PROVIDER_BOUNDED_SUMMARY_MAX_BYTES = DURABLE_RESULT_ENVELOPE_MAX_BYTES
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
_SAFE_TOOLCHAIN_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SAFE_RUNNER_ERROR_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,95}$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROVIDER_REQUEST_KEYS = frozenset(
    {
        "approval_requirement",
        "input_artifact_ids",
        "operation_digest",
        "operation_id",
        "output_dir",
        "params",
        "preprocess_artifact_ids",
        "provider_config_digest",
        "provider_request_id",
        "requested_at",
        "route_policy_id",
        "runtime_packaging_id",
        "sdk_method",
        "selected_backend",
        "source_code_artifact_id",
        "source_code_digest",
    }
)
_PROVIDER_OBSERVATION_KEYS = frozenset(
    {
        "api_version",
        "canonical_error",
        "observation",
        "output_dir",
        "provider",
        "provider_config_digest",
        "provider_request_id",
        "route_policy_id",
        "status",
        "summary",
        "warnings",
    }
)
RepositoryScopeFactory = Callable[[], AbstractContextManager[CoreRepositories]]
EngineRegistryFactory = Callable[[CoreRepositories], Any]


class _HpcToolchainRuntimeIdentityDrift(ValueError):
    """The terminal runner attestation cannot be safely projected."""


def _project_hpc_toolchain_runtime_identity(
    value: Any,
    *,
    execution_mode: str,
    tool_id: str,
    adapter_id: str | None,
    command_template_id: str | None,
) -> dict[str, str] | None:
    if (
        execution_mode != "ssh"
        or not isinstance(value, dict)
        or adapter_id is None
        or command_template_id is None
        or any(
            not isinstance(value.get(field), str)
            for field in _TOOLCHAIN_RUNTIME_IDENTITY_FIELDS
        )
    ):
        return None
    identity = {field: value[field] for field in _TOOLCHAIN_RUNTIME_IDENTITY_FIELDS}
    if (
        identity["schema_id"] != "mcp_hpc_toolchain_runtime_identity@1"
        or identity["attestation_scope"] != "same_ssh_login_shell_pre_exec"
        or identity["execution_mode"] != execution_mode
        or identity["tool_id"] != tool_id
        or identity["adapter_id"] != adapter_id
        or identity["command_template_id"] != command_template_id
        or any(
            _SAFE_TOOLCHAIN_IDENTIFIER.fullmatch(identity[field]) is None
            for field in ("tool_id", "adapter_id", "command_template_id")
        )
        or any(
            _SHA256_DIGEST.fullmatch(identity[field]) is None
            for field in ("runner_contract_digest", "image_digest")
        )
    ):
        return None
    return identity


def _durable_host_context(
    repositories: CoreRepositories,
    execution: ControlledOperationExecution,
) -> SandboxHostCallContext:
    return SandboxHostCallContext(
        repositories=repositories,
        owner=DurableExecutionHostAuthority.from_execution(execution),
    )


def durable_adapter_policy_id(route_policy_id: str) -> str:
    digest = hashlib.sha256(route_policy_id.encode("utf-8")).hexdigest()[:20]
    return f"host_s12_durable_adapter:{digest}:v1"


@dataclass(frozen=True, slots=True)
class HostProviderControlledOperationRouteAdapter:
    route_policy_id: str
    repository_scope_factory: RepositoryScopeFactory
    engine_registry_factory: EngineRegistryFactory
    selected_backend: str = "provider_http"
    adapter_policy_id: str = ""

    def __post_init__(self) -> None:
        if self.route_policy_id not in _PROVIDER_ROUTE_IDS:
            raise ValueError("durable provider route is not a registered live policy")
        expected_policy_id = durable_adapter_policy_id(self.route_policy_id)
        if self.adapter_policy_id and self.adapter_policy_id != expected_policy_id:
            raise ValueError("durable provider adapter policy identity drift")
        object.__setattr__(self, "adapter_policy_id", expected_policy_id)

    def prepare_dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> str:
        identity = {
            "execution_id": execution.execution_id,
            "operation_id": execution.operation_id,
            "operation_digest": execution.operation_digest,
            "dispatch_generation": execution.dispatch_generation,
            "route_policy_id": execution.route_policy_id,
            "request_digest": request.request_digest,
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        return f"provider_req_{digest}"

    def dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        recovered = self._reconcile_persisted(execution)
        if recovered is not None:
            return recovered
        try:
            with self.repository_scope_factory() as repositories:
                operation = repositories.controlled_operations.get(
                    execution.operation_id
                )
                if operation is None:
                    return self._terminal_failure(
                        error_code="durable_operation_missing",
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    )
                engine = self.engine_registry_factory(repositories).require("execution")
                if not callable(
                    getattr(engine, "execute_sandbox_adapter_operation", None)
                ):
                    return self._terminal_failure(
                        error_code="durable_provider_executor_unavailable",
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    )
                envelope = dict(request.request_envelope)
                envelope["_durable_backend_handle_ref"] = execution.backend_handle_ref
                with repositories.controlled_operation_write_fence(execution):
                    raw_result = ExecutionEngineSandboxHostGateway(
                        engine
                    ).execute_adapter_operation(
                        operation=operation,
                        envelope=envelope,
                        context=_durable_host_context(repositories, execution),
                    )
                return self._materialized_from_callback(
                    repositories=repositories,
                    execution=execution,
                    raw_result=raw_result,
                )
        except PipelineSdkFailure as exc:
            recovered = self._reconcile_persisted(execution)
            if recovered is not None:
                return recovered
            if exc.stage in _PROVEN_PRE_EFFECT_PROVIDER_STAGES:
                return self._terminal_failure(
                    error_code=exc.error_type,
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                )
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                backend_handle_ref=execution.backend_handle_ref,
                error_code="durable_provider_dispatch_in_doubt",
                safe_summary=(
                    "Provider dispatch ended without a complete persisted observation."
                ),
            )

    def poll(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        del request
        return self._reconcile_persisted(execution) or DurableRouteObservation(
            kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
            backend_handle_ref=execution.backend_handle_ref,
            error_code="durable_provider_observation_missing",
            safe_summary="The exact provider observation is not yet available.",
        )

    def reconcile(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self.poll(execution, request)

    def materialize(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self.poll(execution, request)

    def _reconcile_persisted(
        self,
        execution: ControlledOperationExecution,
    ) -> DurableRouteObservation | None:
        with self.repository_scope_factory() as repositories:
            records = self._matching_artifacts(
                repositories=repositories,
                execution=execution,
            )
            if not records:
                return None
            relative_names = {
                PurePosixPath(str(record.relative_path)).name for record in records
            }
            has_observation = "provider_observation.json" in relative_names
            has_error = "provider_error.json" in relative_names
            if has_error and has_observation:
                return self._terminal_failure(
                    error_code="durable_provider_terminal_failure",
                    effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                )
            if not has_observation:
                return None
            operation = repositories.controlled_operations.get(execution.operation_id)
            if operation is None:
                return self._terminal_failure(
                    error_code="durable_operation_missing",
                    effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                )
            try:
                adapter_result = self._recover_provider_adapter_result(
                    execution=execution,
                    operation=operation,
                    records=records,
                )
                return self._materialized_from_records(
                    execution=execution,
                    operation=operation,
                    records=records,
                    bounded_summary=dict(adapter_result["bounded_summary"]),
                    adapter_result=adapter_result,
                )
            except PipelineSdkFailure as exc:
                return self._terminal_failure(
                    error_code=exc.error_type,
                    effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                )

    def _recover_provider_adapter_result(
        self,
        *,
        execution: ControlledOperationExecution,
        operation: Any,
        records: tuple[Any, ...],
    ) -> dict[str, Any]:
        ordered_records = tuple(
            sorted(
                records,
                key=lambda record: (
                    str(getattr(record, "created_at", "")),
                    str(record.artifact_id),
                ),
            )
        )
        records_by_name: dict[str, Any] = {}
        seen_paths: set[str] = set()
        for record in ordered_records:
            relative_path = str(record.relative_path)
            parsed_path = PurePosixPath(relative_path)
            if (
                parsed_path.is_absolute()
                or not relative_path
                or any(part in {"", ".", ".."} for part in parsed_path.parts)
                or relative_path in seen_paths
            ):
                self._provider_result_failure(
                    error_type="durable_provider_artifact_set_invalid",
                    message="Durable provider artifact paths are not a unique relative set.",
                )
            seen_paths.add(relative_path)
            if parsed_path.name in {
                "provider_request.json",
                "provider_observation.json",
            }:
                if parsed_path.name in records_by_name:
                    self._provider_result_failure(
                        error_type="durable_provider_artifact_set_invalid",
                        message="Durable provider transcript contains duplicate control documents.",
                    )
                records_by_name[parsed_path.name] = record
        request_record = records_by_name.get("provider_request.json")
        observation_record = records_by_name.get("provider_observation.json")
        if request_record is None or observation_record is None:
            self._provider_result_failure(
                error_type="durable_provider_artifact_set_incomplete",
                message="Durable provider transcript is missing a required control document.",
            )
        request_document = self._read_verified_provider_document(
            request_record,
            document_name="provider_request.json",
        )
        observation_document = self._read_verified_provider_document(
            observation_record,
            document_name="provider_observation.json",
        )
        if frozenset(request_document) != _PROVIDER_REQUEST_KEYS:
            self._provider_result_failure(
                error_type="durable_provider_request_schema_drift",
                message="Persisted provider request schema does not match the frozen contract.",
            )
        if frozenset(observation_document) != _PROVIDER_OBSERVATION_KEYS:
            self._provider_result_failure(
                error_type="durable_provider_observation_schema_drift",
                message="Persisted provider observation schema does not match the frozen contract.",
            )
        route_policy = S12_ROUTE_POLICIES.get(execution.route_policy_id)
        if route_policy is None:
            self._provider_result_failure(
                error_type="durable_provider_route_identity_invalid",
                message="Durable provider route identity is not registered.",
            )
        expected_provider = observation_document.get("provider")
        if (
            not isinstance(expected_provider, str)
            or not expected_provider
            or expected_provider.strip() != expected_provider
        ):
            self._provider_result_failure(
                error_type="durable_provider_route_identity_invalid",
                message="Durable provider observation has no canonical provider identity.",
            )
        expected_sdk_method = (
            f"{route_policy.get('sdk_module')}.{route_policy.get('function_name')}"
        )
        expected_provider_config_digest = str(
            route_policy.get("provider_config_digest") or ""
        )
        expected_runtime_packaging_id = str(
            route_policy.get("runtime_packaging_id") or ""
        )
        identity_checks = (
            request_document.get("provider_request_id") == execution.backend_handle_ref,
            observation_document.get("provider_request_id")
            == execution.backend_handle_ref,
            request_document.get("operation_id") == execution.operation_id,
            request_document.get("operation_digest") == execution.operation_digest,
            request_document.get("route_policy_id") == execution.route_policy_id,
            observation_document.get("route_policy_id") == execution.route_policy_id,
            request_document.get("provider_config_digest")
            == expected_provider_config_digest,
            observation_document.get("provider_config_digest")
            == expected_provider_config_digest,
            request_document.get("runtime_packaging_id")
            == expected_runtime_packaging_id,
            request_document.get("selected_backend") == "provider_http",
            request_document.get("sdk_method") == expected_sdk_method,
            getattr(operation, "operation_id", None) == execution.operation_id,
            getattr(operation, "operation_digest", None) == execution.operation_digest,
            getattr(operation, "route_policy_id", None) == execution.route_policy_id,
        )
        if not all(identity_checks):
            self._provider_result_failure(
                error_type="durable_provider_transcript_identity_drift",
                message="Persisted provider transcript identity drifted from its durable execution.",
            )
        output_dir = request_document.get("output_dir")
        if (
            not isinstance(output_dir, str)
            or not output_dir.startswith("/workspace/output/")
            or observation_document.get("output_dir") != output_dir
        ):
            self._provider_result_failure(
                error_type="durable_provider_output_identity_invalid",
                message="Persisted provider transcript has an invalid output identity.",
            )
        output_dir_relative = output_dir.removeprefix("/workspace/output/")
        output_path = PurePosixPath(output_dir_relative)
        if (
            not output_dir_relative
            or output_path.is_absolute()
            or any(part in {"", ".", ".."} for part in output_path.parts)
        ):
            self._provider_result_failure(
                error_type="durable_provider_output_identity_invalid",
                message="Persisted provider output directory is not canonical.",
            )
        for record in ordered_records:
            metadata = dict(record.metadata or {})
            relative_path = PurePosixPath(str(record.relative_path))
            content_digest = str(metadata.get("content_digest") or "")
            sealed_digest = str(metadata.get("sealed_digest") or "")
            if not relative_path.is_relative_to(output_path):
                self._provider_result_failure(
                    error_type="durable_provider_artifact_identity_drift",
                    message="Persisted provider artifact escaped its frozen output directory.",
                )
            metadata_checks = (
                metadata.get("producer") == "host_supervised_bio_provider",
                metadata.get("controlled_operation_id") == execution.operation_id,
                metadata.get("provider_request_id") == execution.backend_handle_ref,
                metadata.get("route_policy_id") == execution.route_policy_id,
                metadata.get("selected_backend") == "provider_http",
                metadata.get("runtime_packaging_id") == expected_runtime_packaging_id,
                metadata.get("provider_config_digest")
                == expected_provider_config_digest,
                metadata.get("provider") == expected_provider,
                metadata.get("sdk_method") == expected_sdk_method,
                metadata.get("output_dir") == output_dir,
                self._is_sha256_digest(content_digest),
                sealed_digest == content_digest,
            )
            if not all(metadata_checks):
                self._provider_result_failure(
                    error_type="durable_provider_artifact_identity_drift",
                    message="Persisted provider artifact metadata drifted from its durable execution.",
                )
        if (
            observation_document.get("status") != "completed"
            or observation_document.get("canonical_error") is not None
            or not isinstance(observation_document.get("summary"), dict)
            or not isinstance(observation_document.get("observation"), dict)
            or not isinstance(observation_document.get("warnings"), list)
        ):
            self._provider_result_failure(
                error_type="durable_provider_observation_invalid",
                message="Persisted provider observation is not a complete success result.",
            )
        transcript_manifest = {
            "provider_request_id": execution.backend_handle_ref,
            "route_policy_id": execution.route_policy_id,
            "provider_config_digest": expected_provider_config_digest,
            "output_dir": output_dir,
            "files": [
                {
                    "artifact_id": record.artifact_id,
                    "relative_path": record.relative_path,
                    "content_digest": dict(record.metadata or {}).get("content_digest"),
                    "kind": record.kind.value,
                    "format": dict(record.metadata or {}).get("format"),
                }
                for record in ordered_records
            ],
        }
        bounded_summary = {
            **dict(observation_document["summary"]),
            "transcript_manifest": transcript_manifest,
        }
        if expected_sdk_method == "rcsb_pdb.download_structure":
            primary_artifacts = self._recovered_primary_artifact_manifests(
                ordered_records
            )
            if primary_artifacts:
                bounded_summary["artifacts"] = primary_artifacts
        summary_size = len(self._canonical_json_bytes(bounded_summary))
        if summary_size > _PROVIDER_BOUNDED_SUMMARY_MAX_BYTES:
            self._provider_result_failure(
                error_type="durable_provider_bounded_summary_too_large",
                message="Persisted provider summary exceeds the bounded response contract.",
            )
        return {
            "status": "succeeded",
            "provider_request_id": execution.backend_handle_ref,
            "registered_artifact_ids": [
                record.artifact_id for record in ordered_records
            ],
            "output_artifact_ids": [record.artifact_id for record in ordered_records],
            "validation_results": {
                record.artifact_id: dict(
                    dict(record.metadata or {}).get("validation") or {}
                )
                for record in ordered_records
            },
            "bounded_summary": bounded_summary,
            "warnings": list(observation_document["warnings"]),
            "safe_diagnostics_ref": (
                f"artifact://{execution.backend_handle_ref}/provider_observation.json"
            ),
        }

    def _read_verified_provider_document(
        self,
        record: Any,
        *,
        document_name: str,
    ) -> dict[str, Any]:
        metadata = dict(record.metadata or {})
        content_digest = str(metadata.get("content_digest") or "")
        sealed_digest = str(metadata.get("sealed_digest") or "")
        if (
            not self._is_sha256_digest(content_digest)
            or sealed_digest != content_digest
        ):
            self._provider_result_failure(
                error_type="durable_provider_transcript_digest_invalid",
                message="Persisted provider transcript has no exact sealed digest.",
            )
        storage_path = Path(str(getattr(record, "storage_uri", "") or ""))
        try:
            descriptor = os.open(
                storage_path,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            )
        except OSError:
            self._provider_result_failure(
                error_type="durable_provider_transcript_unavailable",
                message="Persisted provider transcript bytes are unavailable.",
            )
        try:
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                file_stat = os.fstat(stream.fileno())
                size_bytes = file_stat.st_size
                if (
                    not stat.S_ISREG(file_stat.st_mode)
                    or size_bytes <= 0
                    or size_bytes > _PROVIDER_TRANSCRIPT_DOCUMENT_MAX_BYTES
                ):
                    self._provider_result_failure(
                        error_type="durable_provider_transcript_size_invalid",
                        message="Persisted provider transcript is not a bounded regular file.",
                    )
                payload = stream.read(_PROVIDER_TRANSCRIPT_DOCUMENT_MAX_BYTES + 1)
        except OSError:
            self._provider_result_failure(
                error_type="durable_provider_transcript_unavailable",
                message="Persisted provider transcript bytes could not be read.",
            )
        if len(payload) != size_bytes:
            self._provider_result_failure(
                error_type="durable_provider_transcript_size_invalid",
                message="Persisted provider transcript changed while being read.",
            )
        actual_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if actual_digest != content_digest:
            self._provider_result_failure(
                error_type="durable_provider_transcript_digest_mismatch",
                message="Persisted provider transcript bytes do not match the catalog digest.",
            )

        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            seen: set[str] = set()
            for key, value in pairs:
                if key in seen:
                    raise ValueError("duplicate JSON object key")
                seen.add(key)
                result[key] = value
            return result

        def reject_constant(value: str) -> Any:
            raise ValueError(f"non-finite JSON constant: {value}")

        try:
            parsed = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=unique_object,
                parse_constant=reject_constant,
            )
        except (UnicodeDecodeError, ValueError):
            self._provider_result_failure(
                error_type="durable_provider_transcript_json_invalid",
                message=f"Persisted {document_name} is not strict JSON.",
            )
        if not isinstance(parsed, dict):
            self._provider_result_failure(
                error_type="durable_provider_transcript_json_invalid",
                message=f"Persisted {document_name} is not a JSON object.",
            )
        return parsed

    @staticmethod
    def _recovered_primary_artifact_manifests(
        records: tuple[Any, ...],
    ) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []
        for record in records:
            metadata = dict(record.metadata or {})
            if metadata.get("primary_output") is not True:
                continue
            provenance = (
                metadata.get("provider_provenance") or metadata.get("provenance") or {}
            )
            manifests.append(
                {
                    "artifact_id": record.artifact_id,
                    "kind": record.kind.value,
                    "relative_path": record.relative_path,
                    "format": metadata.get("format"),
                    "provider": metadata.get("provider"),
                    "external_id": metadata.get("external_id"),
                    "source_locator": metadata.get("source_locator"),
                    "content_digest": metadata.get("content_digest"),
                    "sealed_digest": metadata.get("sealed_digest"),
                    "provenance": provenance,
                    "metadata": {
                        "provider": metadata.get("provider"),
                        "external_id": metadata.get("external_id"),
                        "format": metadata.get("format"),
                        "source_locator": metadata.get("source_locator"),
                        "content_digest": metadata.get("content_digest"),
                        "sealed_digest": metadata.get("sealed_digest"),
                        "provenance": provenance,
                    },
                }
            )
        return manifests

    @staticmethod
    def _canonical_json_bytes(value: Any) -> bytes:
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise PipelineSdkFailure(
                error_type="durable_provider_result_json_invalid",
                message="Durable provider result is not canonical JSON.",
                hint="Preserve the transcript and reject result publication.",
                stage="provider_result_validation",
                retryable=False,
            ) from exc

    @staticmethod
    def _is_sha256_digest(value: str) -> bool:
        return (
            len(value) == 71
            and value.startswith("sha256:")
            and all(character in "0123456789abcdef" for character in value[7:])
        )

    @staticmethod
    def _provider_result_failure(*, error_type: str, message: str) -> NoReturn:
        raise PipelineSdkFailure(
            error_type=error_type,
            message=message,
            hint="Preserve the sealed transcript and reject result publication.",
            stage="provider_result_validation",
            retryable=False,
        )

    def _materialized_from_callback(
        self,
        *,
        repositories: CoreRepositories,
        execution: ControlledOperationExecution,
        raw_result: Any,
    ) -> DurableRouteObservation:
        if not isinstance(raw_result, dict):
            raise PipelineSdkFailure(
                error_type="adapter_result_invalid",
                message="Durable provider executor returned a non-object result.",
                hint="Preserve the execution for exact reconciliation.",
                stage="provider_result_validation",
                retryable=False,
            )
        adapter_result = raw_result.get("adapter_result")
        if not isinstance(adapter_result, dict):
            raise PipelineSdkFailure(
                error_type="adapter_result_invalid",
                message="Durable provider executor omitted its adapter result.",
                hint="Preserve the execution for exact reconciliation.",
                stage="provider_result_validation",
                retryable=False,
            )
        operation = repositories.controlled_operations.get(execution.operation_id)
        if operation is None:
            raise PipelineSdkFailure(
                error_type="durable_operation_missing",
                message="Durable provider operation disappeared before materialization.",
                hint="Preserve the execution for exact reconciliation.",
                stage="provider_result_validation",
                retryable=False,
            )
        registered_artifact_ids = tuple(
            str(value)
            for value in list(adapter_result.get("registered_artifact_ids") or [])
        )
        output_artifact_ids = tuple(
            str(value)
            for value in list(adapter_result.get("output_artifact_ids") or [])
        )
        if (
            not registered_artifact_ids
            or registered_artifact_ids != output_artifact_ids
            or len(set(registered_artifact_ids)) != len(registered_artifact_ids)
        ):
            raise PipelineSdkFailure(
                error_type="provider_artifact_set_incomplete",
                message="Durable provider output artifact identities are incomplete or drifted.",
                hint="Do not publish a partial result; preserve it for reconciliation.",
                stage="provider_result_validation",
                retryable=False,
            )
        if adapter_result.get("provider_request_id") != execution.backend_handle_ref:
            raise PipelineSdkFailure(
                error_type="durable_provider_transcript_identity_drift",
                message="Durable provider callback request identity drifted.",
                hint="Preserve the execution for exact reconciliation.",
                stage="provider_result_validation",
                retryable=False,
            )
        artifact_ids = output_artifact_ids
        records = tuple(
            record
            for artifact_id in artifact_ids
            if (record := repositories.artifacts.get(artifact_id)) is not None
        )
        if len(records) != len(artifact_ids) or not records:
            raise PipelineSdkFailure(
                error_type="provider_artifact_set_incomplete",
                message="Durable provider output artifact set is incomplete.",
                hint="Do not publish a partial result; preserve it for reconciliation.",
                stage="provider_result_validation",
                retryable=False,
            )
        result_summary = raw_result.get("result_summary")
        adapter_bounded_summary = adapter_result.get("bounded_summary")
        if (
            not isinstance(result_summary, dict)
            or not isinstance(adapter_bounded_summary, dict)
            or result_summary != adapter_bounded_summary
        ):
            raise PipelineSdkFailure(
                error_type="provider_result_summary_drift",
                message="Durable provider callback returned inconsistent bounded summaries.",
                hint="Do not publish a result with ambiguous wire identity.",
                stage="provider_result_validation",
                retryable=False,
            )
        return self._materialized_from_records(
            execution=execution,
            operation=operation,
            records=records,
            bounded_summary=dict(result_summary),
            adapter_result=adapter_result,
        )

    def _materialized_from_records(
        self,
        *,
        execution: ControlledOperationExecution,
        operation: Any,
        records: tuple[Any, ...],
        bounded_summary: dict[str, Any],
        adapter_result: dict[str, Any] | None = None,
    ) -> DurableRouteObservation:
        artifact_refs: list[ControlledOperationResultArtifactRef] = []
        for record in sorted(records, key=lambda item: item.artifact_id):
            metadata = dict(record.metadata or {})
            digest = str(
                metadata.get("sealed_digest")
                or metadata.get("content_digest")
                or metadata.get("tree_digest")
                or ""
            )
            if not self._is_sha256_digest(digest):
                raise PipelineSdkFailure(
                    error_type="provider_artifact_digest_missing",
                    message="Durable provider artifact has no exact catalog digest.",
                    hint="Quarantine the incomplete artifact set.",
                    stage="provider_result_validation",
                    retryable=False,
                )
            artifact_refs.append(
                ControlledOperationResultArtifactRef(
                    artifact_id=record.artifact_id,
                    kind=record.kind,
                    relative_path=record.relative_path,
                    artifact_digest=digest,
                )
            )
        immutable_refs = tuple(artifact_refs)
        artifact_set_digest = controlled_operation_artifact_set_digest(immutable_refs)
        if (
            getattr(operation, "operation_id", None) != execution.operation_id
            or getattr(operation, "operation_digest", None)
            != execution.operation_digest
            or not getattr(operation, "sandbox_run_id", None)
            or getattr(operation, "adapter_envelope_schema_version", None)
            != _S12_ADAPTER_ENVELOPE_SCHEMA
        ):
            raise PipelineSdkFailure(
                error_type="durable_provider_operation_identity_drift",
                message="Durable provider operation identity drifted before result materialization.",
                hint="Preserve the execution and reject result publication.",
                stage="provider_result_validation",
                retryable=False,
            )
        canonical_adapter_result = {} if adapter_result is None else adapter_result
        adapter_registered_ids = tuple(
            str(value)
            for value in list(
                canonical_adapter_result.get("registered_artifact_ids") or []
            )
        )
        adapter_output_ids = tuple(
            str(value)
            for value in list(canonical_adapter_result.get("output_artifact_ids") or [])
        )
        immutable_artifact_ids = tuple(ref.artifact_id for ref in immutable_refs)
        validation_results = canonical_adapter_result.get("validation_results")
        warnings = canonical_adapter_result.get("warnings")
        safe_diagnostics_ref = canonical_adapter_result.get("safe_diagnostics_ref")
        if (
            str(canonical_adapter_result.get("status") or "").lower()
            not in _RUNNER_SUCCESS_STATUSES
            or canonical_adapter_result.get("provider_request_id")
            != execution.backend_handle_ref
            or sorted(adapter_registered_ids) != sorted(immutable_artifact_ids)
            or sorted(adapter_output_ids) != sorted(immutable_artifact_ids)
            or not isinstance(validation_results, dict)
            or not isinstance(warnings, list)
            or not isinstance(safe_diagnostics_ref, str)
        ):
            raise PipelineSdkFailure(
                error_type="durable_provider_adapter_result_invalid",
                message="Durable provider adapter result is incomplete or identity-drifted.",
                hint="Preserve the execution and reject result publication.",
                stage="provider_result_validation",
                retryable=False,
            )
        summary_size = len(self._canonical_json_bytes(bounded_summary))
        if summary_size > _PROVIDER_BOUNDED_SUMMARY_MAX_BYTES:
            raise PipelineSdkFailure(
                error_type="durable_provider_bounded_summary_too_large",
                message="Durable provider summary exceeds the bounded response contract.",
                hint="Keep complete data in sealed artifacts and bound the inline summary.",
                stage="provider_result_validation",
                retryable=False,
            )
        raw_envelope = {
            "adapter_envelope_schema_version": _S12_ADAPTER_ENVELOPE_SCHEMA,
            "operation_id": execution.operation_id,
            "operation_digest": execution.operation_digest,
            "sandbox_run_id": getattr(operation, "sandbox_run_id", None),
            "status": "succeeded",
            "result_origin": "host_s12_durable_provider",
            "backend_run_id": None,
            "provider_request_id": execution.backend_handle_ref,
            "fetch_refs": [],
            "registered_artifact_ids": [ref.artifact_id for ref in immutable_refs],
            "output_artifact_ids": [ref.artifact_id for ref in immutable_refs],
            "validation_results": dict(validation_results),
            "bounded_summary": bounded_summary,
            "warnings": list(warnings),
            "error": None,
            "safe_diagnostics_ref": safe_diagnostics_ref,
        }
        safe_envelope = sanitize_public_diagnostic_payload(raw_envelope)
        if not isinstance(safe_envelope, dict):
            raise PipelineSdkFailure(
                error_type="provider_result_projection_invalid",
                message="Durable provider result could not be safely projected.",
                hint="Preserve private evidence and reject public result publication.",
                stage="provider_result_validation",
                retryable=False,
            )
        if len(self._canonical_json_bytes(safe_envelope)) > (
            DURABLE_RESULT_ENVELOPE_MAX_BYTES
        ):
            raise PipelineSdkFailure(
                error_type="durable_provider_result_envelope_too_large",
                message="Durable provider result exceeds the immutable handle bound.",
                hint="Keep complete data in sealed artifacts and bound the inline summary.",
                stage="provider_result_validation",
                retryable=False,
            )
        receipt_digest = self._digest(safe_envelope)
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.RESULT_MATERIALIZED,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            retry_eligibility=RetryEligibility.TERMINAL,
            backend_handle_ref=execution.backend_handle_ref,
            safe_receipt_digest=receipt_digest,
            safe_summary="Provider result and artifact set verified.",
            terminal_outcome=(ControlledOperationExecutionTerminalOutcome.SUCCEEDED),
            materialized_result=DurableRouteMaterializedResult(
                bounded_result_envelope=safe_envelope,
                artifact_set_digest=artifact_set_digest,
                origin="host_s12_durable_provider",
                artifact_refs=immutable_refs,
            ),
        )

    def _matching_artifacts(
        self,
        *,
        repositories: CoreRepositories,
        execution: ControlledOperationExecution,
    ) -> tuple[Any, ...]:
        return tuple(
            record
            for record in repositories.artifacts.list_by_session(execution.session_id)
            if dict(record.metadata or {}).get("controlled_operation_id")
            == execution.operation_id
            and dict(record.metadata or {}).get("provider_request_id")
            == execution.backend_handle_ref
        )

    @staticmethod
    def _terminal_failure(
        *,
        error_code: str,
        effect_certainty: ExternalEffectCertainty,
    ) -> DurableRouteObservation:
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.TERMINAL_FAILURE,
            effect_certainty=effect_certainty,
            retry_eligibility=RetryEligibility.TERMINAL,
            terminal_outcome=ControlledOperationExecutionTerminalOutcome.FAILED,
            error_code=error_code,
            safe_summary="The durable provider operation failed without a canonical result.",
        )

    @staticmethod
    def _digest(value: Any) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class _ExactReservedOutcomeRunner:
    """Replays one observed outcome into Host persistence without a new effect."""

    run_id: str
    outcome: Any
    submit_count: int = 0

    def submit_reserved_execution(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        run_id: str,
    ) -> Any:
        del session_id, payload
        if run_id != self.run_id or str(getattr(self.outcome, "run_id", "")) != run_id:
            raise ValueError("recovered runner outcome identity drift")
        self.submit_count += 1
        if self.submit_count != 1:
            raise RuntimeError("recovered runner outcome was consumed more than once")
        return self.outcome

    def submit_execution(self, session_id: str, payload: dict[str, Any]) -> Any:
        del session_id, payload
        raise RuntimeError("exact outcome recovery cannot dispatch a new execution")


@dataclass(frozen=True, slots=True)
class HostHpcControlledOperationRouteAdapter:
    route_policy_id: str
    repository_scope_factory: RepositoryScopeFactory
    engine_registry_factory: EngineRegistryFactory
    selected_backend: str = "hpc"
    adapter_policy_id: str = ""

    def __post_init__(self) -> None:
        if self.route_policy_id not in _HPC_ROUTE_IDS:
            raise ValueError("durable HPC route is not a registered live policy")
        expected_policy_id = durable_adapter_policy_id(self.route_policy_id)
        if self.adapter_policy_id and self.adapter_policy_id != expected_policy_id:
            raise ValueError("durable HPC adapter policy identity drift")
        object.__setattr__(self, "adapter_policy_id", expected_policy_id)

    def prepare_dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> str:
        if execution.approval_digest is None:
            raise ValueError("durable HPC execution has no frozen approval digest")
        identity = {
            "schema_version": "runner_execution_reservation_identity@1",
            "execution_id": execution.execution_id,
            "operation_id": execution.operation_id,
            "operation_digest": execution.operation_digest,
            "approval_digest": execution.approval_digest,
            "route_policy_id": execution.route_policy_id,
            "adapter_policy_id": execution.adapter_policy_id,
            "request_digest": request.request_digest,
            "execution_mode": self._execution_mode(),
        }
        with self.repository_scope_factory() as repositories:
            operation = self._require_operation(repositories, execution)
            del operation
            runner = self._require_runner(repositories)
            reserve = getattr(runner, "reserve_execution", None)
            if not callable(reserve):
                raise RuntimeError("HPC runner does not support durable reservation")
            reservation = reserve(identity)
        if not isinstance(reservation, dict):
            raise ValueError("HPC runner returned an invalid reservation")
        run_id = str(reservation.get("run_id") or "")
        if not run_id or str(reservation.get("identity_digest") or "") != self._digest(
            identity
        ):
            raise ValueError("HPC runner reservation identity drift")
        return run_id

    def dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        try:
            with self.repository_scope_factory() as repositories:
                operation = self._require_operation(repositories, execution)
                engine = self.engine_registry_factory(repositories).require("execution")
                runner = self._runner_from_engine(engine)
                observation = self._inspect_runner(runner, execution)
                if str(getattr(observation, "status", "")) != "reserved":
                    return self._observation_from_runner(
                        execution=execution,
                        request=request,
                        observation=observation,
                        engine=engine,
                        runner=runner,
                        operation=operation,
                        repositories=repositories,
                    )
                if not callable(
                    getattr(engine, "execute_sandbox_adapter_operation", None)
                ):
                    return self._terminal_failure(
                        error_code="durable_hpc_executor_unavailable",
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    )
                envelope = dict(request.request_envelope)
                envelope["_durable_backend_handle_ref"] = execution.backend_handle_ref
                with repositories.controlled_operation_write_fence(execution):
                    ExecutionEngineSandboxHostGateway(engine).execute_adapter_operation(
                        operation=operation,
                        envelope=envelope,
                        context=_durable_host_context(repositories, execution),
                    )
                observation = self._inspect_runner(runner, execution)
                return self._observation_from_runner(
                    execution=execution,
                    request=request,
                    observation=observation,
                    engine=engine,
                    runner=runner,
                    operation=operation,
                    repositories=repositories,
                )
        except Exception as exc:  # noqa: BLE001 - classify local DB separately.
            if is_transient_sqlite_contention(exc):
                raise
            return self._observe_exact(execution, request)

    def poll(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self._observe_exact(execution, request)

    def reconcile(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self._observe_exact(execution, request)

    def materialize(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self._observe_exact(execution, request)

    def _observe_exact(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        try:
            with self.repository_scope_factory() as repositories:
                operation = self._require_operation(repositories, execution)
                engine = self.engine_registry_factory(repositories).require("execution")
                runner = self._runner_from_engine(engine)
                observation = self._inspect_runner(runner, execution)
                return self._observation_from_runner(
                    execution=execution,
                    request=request,
                    observation=observation,
                    engine=engine,
                    runner=runner,
                    operation=operation,
                    repositories=repositories,
                )
        except Exception as exc:  # noqa: BLE001 - classify local DB separately.
            if is_transient_sqlite_contention(exc):
                raise
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                backend_handle_ref=execution.backend_handle_ref,
                error_code="durable_hpc_observation_unavailable",
                safe_summary="The exact runner observation is unavailable.",
            )

    def _observation_from_runner(
        self,
        *,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
        observation: Any,
        engine: Any,
        runner: Any,
        operation: Any,
        repositories: CoreRepositories,
    ) -> DurableRouteObservation:
        status = str(getattr(observation, "status", ""))
        effect = str(getattr(observation, "effect_certainty", ""))
        retry = str(getattr(observation, "retry_eligibility", ""))
        receipt = self._receipt(observation)
        if status == "reserved" or (
            effect == ExternalEffectCertainty.NO_EFFECT.value
            and retry == RetryEligibility.SAME_PHASE_SAFE.value
        ):
            if execution.dispatch_generation >= 2:
                return self._terminal_failure(
                    error_code="durable_hpc_pre_effect_budget_exhausted",
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    backend_handle_ref=execution.backend_handle_ref,
                    safe_receipt_digest=receipt,
                )
            if receipt is None:
                return DurableRouteObservation(
                    kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                    effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                    retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                    backend_handle_ref=execution.backend_handle_ref,
                    error_code="durable_hpc_no_effect_proof_missing",
                    safe_summary="The runner did not provide an exact no-effect receipt.",
                )
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.PROVEN_NO_EFFECT,
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=receipt,
                safe_summary="The exact runner reservation proves no external effect.",
            )
        if (
            bool(getattr(observation, "reconciliation_required", False))
            or effect == ExternalEffectCertainty.DISPATCH_IN_DOUBT.value
        ):
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=receipt,
                error_code="durable_hpc_dispatch_in_doubt",
                safe_summary="The direct runner dispatch outcome is unknown and will not be replayed.",
            )
        if status in _RUNNER_ACTIVE_STATUSES:
            if (
                effect == ExternalEffectCertainty.TERMINAL_KNOWN.value
                and retry == RetryEligibility.VERIFY_THEN_RETRY.value
            ):
                local = self._recover_terminal_result(
                    execution=execution,
                    request=request,
                    engine=engine,
                    runner=runner,
                    operation=operation,
                    repositories=repositories,
                    safe_receipt_digest=receipt,
                )
                if local is not None:
                    return local
                return DurableRouteObservation(
                    kind=DurableRouteObservationKind.RESULT_PENDING,
                    effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                    retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                    backend_handle_ref=execution.backend_handle_ref,
                    safe_receipt_digest=receipt,
                    error_code="durable_hpc_output_fetch_pending",
                    safe_summary=(
                        "The payload is terminal; exact output recovery remains pending."
                    ),
                )
            if effect != ExternalEffectCertainty.EFFECT_KNOWN.value:
                return DurableRouteObservation(
                    kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                    effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                    retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                    backend_handle_ref=execution.backend_handle_ref,
                    safe_receipt_digest=receipt,
                    error_code="durable_hpc_active_state_incomplete",
                    safe_summary="The runner active state lacks a complete effect proof.",
                )
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.WAITING_EXTERNAL,
                effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=receipt,
                safe_summary="The exact runner execution remains active.",
            )
        if status in _RUNNER_SUCCESS_STATUSES:
            local = self._recover_terminal_result(
                execution=execution,
                request=request,
                engine=engine,
                runner=runner,
                operation=operation,
                repositories=repositories,
                safe_receipt_digest=receipt,
            )
            if local is not None:
                return local
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RESULT_PENDING,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=receipt,
                error_code="durable_hpc_result_staging_pending",
                safe_summary="The runner succeeded; Host result materialization is pending.",
            )
        if status in _RUNNER_TERMINAL_FAILURE_STATUSES:
            certainty = (
                ExternalEffectCertainty.NO_EFFECT
                if effect == ExternalEffectCertainty.NO_EFFECT.value
                else ExternalEffectCertainty.TERMINAL_KNOWN
            )
            raw_error_code = getattr(observation, "error_code", None)
            if raw_error_code is None:
                error_code = "durable_hpc_terminal_failure"
            elif (
                isinstance(raw_error_code, str)
                and _SAFE_RUNNER_ERROR_CODE.fullmatch(raw_error_code) is not None
            ):
                error_code = raw_error_code
            else:
                error_code = "durable_hpc_runner_causal_projection_invalid"
            terminal_outcome = (
                ControlledOperationExecutionTerminalOutcome.CANCELLED
                if status in {"cancelled", "canceled"}
                else ControlledOperationExecutionTerminalOutcome.FAILED
            )
            return self._terminal_failure(
                error_code=error_code,
                effect_certainty=certainty,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=receipt,
                terminal_outcome=terminal_outcome,
            )
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
            backend_handle_ref=execution.backend_handle_ref,
            safe_receipt_digest=receipt,
            error_code="durable_hpc_runner_state_unknown",
            safe_summary="The runner returned an unsupported closed state.",
        )

    def _recover_terminal_result(
        self,
        *,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
        engine: Any,
        runner: Any,
        operation: Any,
        repositories: CoreRepositories,
        safe_receipt_digest: str | None,
    ) -> DurableRouteObservation | None:
        local = self._local_observation(
            execution,
            repositories=repositories,
            engine=engine,
            safe_receipt_digest=safe_receipt_digest,
        )
        if local is not None:
            return local
        recover = getattr(runner, "recover_reserved_execution_outcome", None)
        callback = getattr(engine, "execute_sandbox_adapter_operation", None)
        if not callable(recover) or not callable(callback):
            return None
        try:
            outcome = recover(run_id=str(execution.backend_handle_ref or ""))
            proxy = _ExactReservedOutcomeRunner(
                run_id=str(execution.backend_handle_ref or ""),
                outcome=outcome,
            )
            recovery_engine = replace(engine, runner=proxy)
            envelope = dict(request.request_envelope)
            envelope["_durable_backend_handle_ref"] = execution.backend_handle_ref
            with repositories.controlled_operation_write_fence(execution):
                ExecutionEngineSandboxHostGateway(
                    recovery_engine
                ).execute_adapter_operation(
                    operation=operation,
                    envelope=envelope,
                    context=_durable_host_context(repositories, execution),
                )
            if proxy.submit_count != 1:
                return None
        except Exception as exc:  # noqa: BLE001 - retain terminal effect state.
            if is_transient_sqlite_contention(exc):
                raise
            return None
        return self._local_observation(
            execution,
            repositories=repositories,
            engine=recovery_engine,
            safe_receipt_digest=safe_receipt_digest,
        )

    def _local_observation(
        self,
        execution: ControlledOperationExecution,
        *,
        repositories: CoreRepositories | None = None,
        engine: Any | None = None,
        safe_receipt_digest: str | None = None,
    ) -> DurableRouteObservation | None:
        if execution.backend_handle_ref is None:
            return None
        if repositories is None:
            with self.repository_scope_factory() as scoped_repositories:
                scoped_engine = self.engine_registry_factory(
                    scoped_repositories
                ).require("execution")
                return self._local_observation(
                    execution,
                    repositories=scoped_repositories,
                    engine=scoped_engine,
                    safe_receipt_digest=safe_receipt_digest,
                )
        operation = self._require_operation(repositories, execution)
        expected_invocation_id = f"inv_sandbox_adapter_{execution.operation_id}"
        matches = [
            run
            for run in repositories.runs.list_by_session(execution.session_id)
            if run.runner_run_id == execution.backend_handle_ref
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("reserved runner identity has multiple Host runs")
        run = matches[0]
        if (
            run.invocation_id != expected_invocation_id
            or run.approval_id != execution.approval_id
        ):
            raise ValueError("reserved runner identity belongs to another Host context")
        if run.status in {RunStatus.FAILED, RunStatus.CANCELLED}:
            return self._terminal_failure(
                error_code="durable_hpc_terminal_failure",
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=safe_receipt_digest,
                terminal_outcome=(
                    ControlledOperationExecutionTerminalOutcome.CANCELLED
                    if run.status is RunStatus.CANCELLED
                    else ControlledOperationExecutionTerminalOutcome.FAILED
                ),
            )
        if run.status is not RunStatus.SUCCEEDED:
            return None
        document_id = (
            "hpc_pending_" + hashlib.sha256(run.run_id.encode("utf-8")).hexdigest()[:24]
        )
        document = repositories.engine_documents.get(document_id)
        if (
            document is None
            or document.session_id != execution.session_id
            or document.invocation_id != expected_invocation_id
            or document.document_kind != "hpc_pending_outputs"
        ):
            return None
        pending = dict(document.payload)
        if (
            str(pending.get("run_id") or "") != run.run_id
            or str(pending.get("runner_run_id") or "") != execution.backend_handle_ref
            or str(pending.get("hpc_workspace_id") or "")
            != str(operation.hpc_workspace_id or "")
            or pending.get("selected_backend") != "hpc"
            or pending.get("status") != RunStatus.SUCCEEDED.value
        ):
            raise ValueError("Host HPC result identity drift")
        fetch_callback = getattr(engine, "fetch_sandbox_hpc_outputs", None)
        if not callable(fetch_callback):
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RESULT_PENDING,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=safe_receipt_digest,
                error_code="durable_hpc_output_fetch_unavailable",
                safe_summary="The runner is terminal; Host output fetch is unavailable.",
            )
        try:
            with repositories.controlled_operation_write_fence(execution):
                fetch_result = ExecutionEngineSandboxHostGateway(
                    engine
                ).fetch_hpc_outputs(
                    params={
                        "session_id": execution.session_id,
                        "sandbox_workspace_id": operation.sandbox_workspace_id,
                        "hpc_workspace": {
                            "kind": "hpc_workspace",
                            "hpc_workspace_id": operation.hpc_workspace_id,
                            "sandbox_workspace_id": operation.sandbox_workspace_id,
                        },
                        "run_id": run.run_id,
                        "operation_id": execution.operation_id,
                        "operation_digest": execution.operation_digest,
                    },
                    context=_durable_host_context(repositories, execution),
                )
        except Exception as exc:  # noqa: BLE001 - terminal effect; staging may retry.
            if is_transient_sqlite_contention(exc):
                raise
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RESULT_PENDING,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=safe_receipt_digest,
                error_code="durable_hpc_output_fetch_pending",
                safe_summary="The runner is terminal; exact output staging remains pending.",
            )
        if not isinstance(fetch_result, dict):
            raise ValueError("Host HPC output fetch returned an invalid result")
        try:
            return self._materialized_local_result(
                repositories=repositories,
                execution=execution,
                operation=operation,
                run=run,
                pending=pending,
                fetch_result=fetch_result,
                safe_receipt_digest=safe_receipt_digest,
            )
        except _HpcToolchainRuntimeIdentityDrift:
            return self._terminal_failure(
                error_code="durable_hpc_toolchain_runtime_identity_invalid",
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=safe_receipt_digest,
                terminal_outcome=ControlledOperationExecutionTerminalOutcome.FAILED,
            )
        except (TypeError, ValueError, KeyError):
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RESULT_PENDING,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=safe_receipt_digest,
                error_code="durable_hpc_artifact_set_validation_pending",
                safe_summary=(
                    "The runner is terminal; the catalog artifact set is not "
                    "yet canonical."
                ),
            )

    def _materialized_local_result(
        self,
        *,
        repositories: CoreRepositories,
        execution: ControlledOperationExecution,
        operation: Any,
        run: Any,
        pending: dict[str, Any],
        fetch_result: dict[str, Any],
        safe_receipt_digest: str | None,
    ) -> DurableRouteObservation:
        declared_outputs = [
            dict(item)
            for item in list(pending.get("declared_outputs") or [])
            if isinstance(item, dict)
        ]
        stage_refs = [
            dict(item)
            for item in list(pending.get("stage_refs") or [])
            if isinstance(item, dict)
        ]
        request_metadata = dict(pending.get("request_metadata") or {})
        raw_result = dict(pending.get("raw_result") or {})
        if safe_receipt_digest is None:
            candidate_receipt = raw_result.get("runner_attempt_receipt_digest")
            if isinstance(candidate_receipt, str) and candidate_receipt.startswith(
                "sha256:"
            ):
                safe_receipt_digest = candidate_receipt
        tool_id = str(
            request_metadata.get("catalog_tool_id")
            or f"{operation.sdk_module}.{operation.function_name}"
        )
        if (
            fetch_result.get("kind") != "hpc_fetch_result"
            or str(fetch_result.get("run_id") or "") != run.run_id
            or str(fetch_result.get("hpc_workspace_id") or "")
            != str(operation.hpc_workspace_id or "")
            or str(fetch_result.get("operation_id") or "") != execution.operation_id
            or str(fetch_result.get("operation_digest") or "")
            != execution.operation_digest
        ):
            raise ValueError("Host HPC fetch result identity drift")
        artifact_ids = tuple(
            str(value)
            for value in list(fetch_result.get("registered_artifact_ids") or [])
        )
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("Host HPC fetch result contains duplicate artifacts")
        expected_output_paths = {
            str(item.get("relative_path") or "")
            for item in list(pending.get("outputs") or [])
            if isinstance(item, dict)
        }
        if expected_output_paths and not artifact_ids:
            raise ValueError("Host HPC fetch result omitted declared artifacts")
        artifact_refs: list[ControlledOperationResultArtifactRef] = []
        observed_output_paths: set[str] = set()
        for artifact_id in sorted(artifact_ids):
            record = repositories.artifacts.get(artifact_id)
            if record is None or record.session_id != execution.session_id:
                raise ValueError("Host HPC fetch artifact is missing from the catalog")
            metadata = dict(record.metadata or {})
            if (
                record.run_id != run.run_id
                or metadata.get("controlled_operation_id") != execution.operation_id
                or metadata.get("controlled_operation_digest")
                != execution.operation_digest
                or metadata.get("pipeline_invocation_id")
                != f"inv_sandbox_adapter_{execution.operation_id}"
                or metadata.get("runner_run_id") != execution.backend_handle_ref
                or metadata.get("hpc_workspace_id") != operation.hpc_workspace_id
            ):
                raise ValueError("Host HPC fetch artifact identity drift")
            artifact_digest = str(
                metadata.get("sealed_digest")
                or metadata.get("content_digest")
                or metadata.get("tree_digest")
                or ""
            )
            if not artifact_digest.startswith("sha256:") or len(artifact_digest) != 71:
                raise ValueError("Host HPC fetch artifact has no exact catalog digest")
            observed_output_paths.add(str(metadata.get("declared_output_path") or ""))
            artifact_refs.append(
                ControlledOperationResultArtifactRef(
                    artifact_id=record.artifact_id,
                    kind=record.kind,
                    relative_path=record.relative_path,
                    artifact_digest=artifact_digest,
                )
            )
        if expected_output_paths != observed_output_paths:
            raise ValueError("Host HPC declared output artifact set drift")
        immutable_refs = tuple(artifact_refs)
        envelope = {
            "kind": "hpc_run_handle",
            "tool_id": tool_id,
            "run_id": run.run_id,
            "status": run.status.value,
            "execution_mode": run.execution_mode,
            "exit_code": raw_result.get("exit_code"),
            "operation_key": pending.get("operation_key"),
            "placement": "hpc",
            "hpc_workspace_id": operation.hpc_workspace_id,
            "declared_outputs": declared_outputs,
            "stage_refs": stage_refs,
            "registered_artifact_ids": [ref.artifact_id for ref in immutable_refs],
            "output_artifact_ids": [ref.artifact_id for ref in immutable_refs],
            "fetch_refs": list(fetch_result.get("fetch_refs") or []),
            "route_policy_id": operation.route_policy_id,
            "selected_backend": "hpc",
            "runtime_packaging_id": operation.runtime_packaging_id,
            "toolchain_id": operation.toolchain_id,
            "summary": run.summary or "HPC placement operation succeeded",
            "warnings": [],
        }
        raw_runtime_identity = raw_result.get("toolchain_runtime_identity")
        if raw_runtime_identity is not None:
            tool_contract = request_metadata.get("tool_contract")
            expected_adapter_id = (
                tool_contract.get("adapter_id")
                if isinstance(tool_contract, dict)
                and isinstance(tool_contract.get("adapter_id"), str)
                else None
            )
            expected_command_template_id = (
                tool_contract.get("command_template_id")
                if isinstance(tool_contract, dict)
                and isinstance(tool_contract.get("command_template_id"), str)
                else None
            )
            runtime_identity = _project_hpc_toolchain_runtime_identity(
                raw_runtime_identity,
                execution_mode=str(run.execution_mode),
                tool_id=tool_id,
                adapter_id=expected_adapter_id,
                command_template_id=expected_command_template_id,
            )
            if runtime_identity is None:
                raise _HpcToolchainRuntimeIdentityDrift(
                    "Host HPC toolchain runtime identity drift"
                )
            envelope["toolchain_runtime_identity"] = runtime_identity
        safe_envelope = sanitize_public_diagnostic_payload(envelope)
        if not isinstance(safe_envelope, dict):
            raise ValueError("Host HPC result projection is invalid")
        artifact_set_digest = controlled_operation_artifact_set_digest(immutable_refs)
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.RESULT_MATERIALIZED,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            retry_eligibility=RetryEligibility.TERMINAL,
            backend_handle_ref=execution.backend_handle_ref,
            safe_receipt_digest=safe_receipt_digest,
            safe_summary="Runner result and declared output set verified.",
            terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
            materialized_result=DurableRouteMaterializedResult(
                bounded_result_envelope=safe_envelope,
                artifact_set_digest=artifact_set_digest,
                origin="host_s12_durable_hpc",
                artifact_refs=immutable_refs,
            ),
        )

    def _require_operation(
        self,
        repositories: CoreRepositories,
        execution: ControlledOperationExecution,
    ) -> Any:
        operation = repositories.controlled_operations.get(execution.operation_id)
        if (
            operation is None
            or operation.session_id != execution.session_id
            or operation.operation_digest != execution.operation_digest
            or operation.route_policy_id != execution.route_policy_id
            or operation.selected_backend != "hpc"
        ):
            raise ValueError("durable HPC operation identity drift")
        return operation

    def _require_runner(self, repositories: CoreRepositories) -> Any:
        engine = self.engine_registry_factory(repositories).require("execution")
        return self._runner_from_engine(engine)

    @staticmethod
    def _runner_from_engine(engine: Any) -> Any:
        runner = getattr(engine, "runner", None)
        if runner is None:
            raise RuntimeError("execution engine has no HPC runner")
        return runner

    @staticmethod
    def _inspect_runner(runner: Any, execution: ControlledOperationExecution) -> Any:
        inspect = getattr(runner, "inspect_reserved_execution", None)
        if not callable(inspect) or execution.backend_handle_ref is None:
            raise RuntimeError("HPC runner does not support exact inspection")
        observation = inspect(run_id=execution.backend_handle_ref)
        if str(getattr(observation, "run_id", "")) != execution.backend_handle_ref:
            raise ValueError("HPC runner observation identity drift")
        return observation

    @staticmethod
    def _receipt(observation: Any) -> str | None:
        value = getattr(observation, "runner_attempt_receipt_digest", None)
        return None if value is None else str(value)

    def _execution_mode(self) -> str:
        policy = dict(S12_ROUTE_POLICIES[self.route_policy_id])
        return "ssh" if policy.get("sdk_module") == "bio_tools" else "auto"

    @staticmethod
    def _terminal_failure(
        *,
        error_code: str,
        effect_certainty: ExternalEffectCertainty,
        backend_handle_ref: str | None = None,
        safe_receipt_digest: str | None = None,
        terminal_outcome: ControlledOperationExecutionTerminalOutcome = (
            ControlledOperationExecutionTerminalOutcome.FAILED
        ),
    ) -> DurableRouteObservation:
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.TERMINAL_FAILURE,
            effect_certainty=effect_certainty,
            retry_eligibility=RetryEligibility.TERMINAL,
            backend_handle_ref=backend_handle_ref,
            safe_receipt_digest=safe_receipt_digest,
            terminal_outcome=terminal_outcome,
            error_code=error_code,
            safe_summary="The durable HPC operation reached a closed failure.",
        )

    @staticmethod
    def _digest(value: Any) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_host_provider_route_adapters(
    *,
    route_policy_ids: tuple[str, ...],
    repository_scope_factory: RepositoryScopeFactory,
    engine_registry_factory: EngineRegistryFactory,
) -> dict[str, ControlledOperationRouteAdapter]:
    return {
        route_policy_id: HostProviderControlledOperationRouteAdapter(
            route_policy_id=route_policy_id,
            repository_scope_factory=repository_scope_factory,
            engine_registry_factory=engine_registry_factory,
        )
        for route_policy_id in sorted(set(route_policy_ids) & _PROVIDER_ROUTE_IDS)
    }


def build_host_hpc_route_adapters(
    *,
    route_policy_ids: tuple[str, ...],
    repository_scope_factory: RepositoryScopeFactory,
    engine_registry_factory: EngineRegistryFactory,
) -> dict[str, ControlledOperationRouteAdapter]:
    return {
        route_policy_id: HostHpcControlledOperationRouteAdapter(
            route_policy_id=route_policy_id,
            repository_scope_factory=repository_scope_factory,
            engine_registry_factory=engine_registry_factory,
        )
        for route_policy_id in sorted(set(route_policy_ids) & _HPC_ROUTE_IDS)
    }


__all__ = [
    "HostHpcControlledOperationRouteAdapter",
    "HostProviderControlledOperationRouteAdapter",
    "build_host_hpc_route_adapters",
    "build_host_provider_route_adapters",
    "durable_adapter_policy_id",
]
