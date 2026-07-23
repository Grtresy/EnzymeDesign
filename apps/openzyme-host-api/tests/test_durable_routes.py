from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from openzyme_core import DurableRouteObservationKind
from openzyme_core import ControlledOperationExecutionWorker
from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperationDispatchRequest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import RetryEligibility
from openzyme_domain import RunStatus
from openzyme_engines.execution import PipelineSdkFailure
from openzyme_host_api.durable_routes import (
    HostHpcControlledOperationRouteAdapter,
)
from openzyme_host_api.durable_routes import (
    HostProviderControlledOperationRouteAdapter,
)
from openzyme_host_api.durable_routes import durable_adapter_policy_id


_TOOLCHAIN_RUNTIME_IDENTITY = {
    "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
    "attestation_scope": "same_ssh_login_shell_pre_exec",
    "execution_mode": "ssh",
    "tool_id": "bio_tools.mafft",
    "adapter_id": "bio_tools.mafft",
    "command_template_id": "bio_tools_mafft_sif_v1",
    "runner_contract_digest": "sha256:" + "6" * 64,
    "image_digest": "sha256:" + "7" * 64,
}


class _FakeRepositories(SimpleNamespace):
    @contextmanager
    def controlled_operation_write_fence(
        self,
        execution: ControlledOperationExecution,
    ):  # type: ignore[no-untyped-def]
        assert execution.lease_token is not None or execution.state_version > 0
        yield


class _ArtifactRepository:
    def __init__(self) -> None:
        self.records: dict[str, object] = {}

    def get(self, artifact_id: str):  # type: ignore[no-untyped-def]
        return self.records.get(artifact_id)

    def list_by_session(self, session_id: str) -> list[object]:
        return [
            record
            for record in self.records.values()
            if record.session_id == session_id  # type: ignore[attr-defined]
        ]


class _OperationRepository:
    def __init__(self, operation: object) -> None:
        self.operation = operation

    def get(self, operation_id: str):  # type: ignore[no-untyped-def]
        if operation_id == self.operation.operation_id:  # type: ignore[attr-defined]
            return self.operation
        return None


@dataclass
class _FakeExecutionEngine:
    artifacts: _ArtifactRepository
    artifact_root: Path
    repositories: object | None = None
    sandbox_host_call_context_factory: object | None = None
    lose_callback: bool = False
    tamper_observation: bool = False
    symlink_observation: bool = False
    observation_extra: dict[str, object] = field(default_factory=dict)
    _state: dict[str, object] = field(
        default_factory=lambda: {"call_count": 0, "seen_handle": None}
    )

    @property
    def call_count(self) -> int:
        return int(self._state["call_count"])

    @property
    def seen_handle(self) -> str | None:
        value = self._state["seen_handle"]
        return None if value is None else str(value)

    def execute_sandbox_adapter_operation(
        self,
        operation: object,
        envelope: dict[str, object],
    ) -> dict[str, object]:
        assert self.sandbox_host_call_context_factory is None
        self._state["call_count"] = self.call_count + 1
        self._state["seen_handle"] = str(envelope["_durable_backend_handle_ref"])
        output_dir = "/workspace/output/provider/ncbi"
        request_document = {
            "approval_requirement": {"required": True},
            "input_artifact_ids": [],
            "operation_digest": operation.operation_digest,
            "operation_id": operation.operation_id,
            "output_dir": output_dir,
            "params": {"accessions": ["P12345"]},
            "preprocess_artifact_ids": [],
            "provider_config_digest": "provider_config:ncbi:v1",
            "provider_request_id": self.seen_handle,
            "requested_at": "2026-07-21T00:00:01+00:00",
            "route_policy_id": "bio.ncbi_fetch_proteins.provider:v1",
            "runtime_packaging_id": "provider_http:v1",
            "sdk_method": "bio.ncbi_fetch_proteins",
            "selected_backend": "provider_http",
            "source_code_artifact_id": None,
            "source_code_digest": None,
        }
        summary = {"provider": "ncbi", "record_count": 1}
        observation_document = {
            "api_version": "fixture",
            "canonical_error": None,
            "observation": {"requests": []},
            "output_dir": output_dir,
            "provider": "ncbi",
            "provider_config_digest": "provider_config:ncbi:v1",
            "provider_request_id": self.seen_handle,
            "route_policy_id": "bio.ncbi_fetch_proteins.provider:v1",
            "status": "completed",
            "summary": summary,
            "warnings": [],
            **self.observation_extra,
        }
        records = (
            self._persist_artifact(
                operation=operation,
                artifact_id="artifact_provider_request",
                relative_path="provider/ncbi/provider_request.json",
                content=(json.dumps(request_document, sort_keys=True) + "\n").encode(),
                kind=ArtifactKind.RESULT,
                format_name="json",
                created_at="2026-07-21T00:00:01+00:00",
                transcript_file="provider_request.json",
            ),
            self._persist_artifact(
                operation=operation,
                artifact_id="artifact_provider_fasta",
                relative_path="provider/ncbi/provider_parsed/proteins.fasta",
                content=b">P12345\nMPEPTIDE\n",
                kind=ArtifactKind.SEQUENCE,
                format_name="fasta",
                created_at="2026-07-21T00:00:02+00:00",
            ),
            self._persist_artifact(
                operation=operation,
                artifact_id="artifact_provider_observation",
                relative_path="provider/ncbi/provider_observation.json",
                content=(
                    json.dumps(observation_document, sort_keys=True) + "\n"
                ).encode(),
                kind=ArtifactKind.RESULT,
                format_name="json",
                created_at="2026-07-21T00:00:03+00:00",
                transcript_file="provider_observation.json",
            ),
        )
        transcript_manifest = {
            "provider_request_id": self.seen_handle,
            "route_policy_id": "bio.ncbi_fetch_proteins.provider:v1",
            "provider_config_digest": "provider_config:ncbi:v1",
            "output_dir": output_dir,
            "files": [
                {
                    "artifact_id": record.artifact_id,
                    "relative_path": record.relative_path,
                    "content_digest": record.metadata["content_digest"],
                    "kind": record.kind.value,
                    "format": record.metadata["format"],
                }
                for record in records
            ],
        }
        bounded_summary = {
            **summary,
            "transcript_manifest": transcript_manifest,
        }
        adapter_result = {
            "status": "succeeded",
            "provider_request_id": self.seen_handle,
            "registered_artifact_ids": [record.artifact_id for record in records],
            "output_artifact_ids": [record.artifact_id for record in records],
            "validation_results": {
                record.artifact_id: record.metadata["validation"] for record in records
            },
            "bounded_summary": bounded_summary,
            "warnings": [],
            "safe_diagnostics_ref": (
                f"artifact://{self.seen_handle}/provider_observation.json"
            ),
        }
        if self.tamper_observation:
            Path(records[-1].storage_uri).write_text("{}\n", encoding="utf-8")
        if self.symlink_observation:
            observation_path = Path(records[-1].storage_uri)
            target_path = observation_path.with_name(observation_path.name + "-target")
            target_path.write_bytes(observation_path.read_bytes())
            observation_path.unlink()
            observation_path.symlink_to(target_path)
        if self.lose_callback:
            raise PipelineSdkFailure(
                error_type="simulated_provider_callback_loss",
                message="simulated callback loss after provider artifacts persisted",
                hint="reconcile the exact provider request",
                stage="provider_result_validation",
                retryable=False,
            )
        return {
            "adapter_result": adapter_result,
            "result_summary": bounded_summary,
        }

    def _persist_artifact(
        self,
        *,
        operation: object,
        artifact_id: str,
        relative_path: str,
        content: bytes,
        kind: ArtifactKind,
        format_name: str,
        created_at: str,
        transcript_file: str | None = None,
    ) -> object:
        storage_path = self.artifact_root / artifact_id
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(content)
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        metadata = {
            "producer": "host_supervised_bio_provider",
            "controlled_operation_id": operation.operation_id,
            "provider_request_id": self.seen_handle,
            "route_policy_id": "bio.ncbi_fetch_proteins.provider:v1",
            "selected_backend": "provider_http",
            "runtime_packaging_id": "provider_http:v1",
            "provider_config_digest": "provider_config:ncbi:v1",
            "provider": "ncbi",
            "sdk_method": "bio.ncbi_fetch_proteins",
            "output_dir": "/workspace/output/provider/ncbi",
            "content_digest": digest,
            "sealed_digest": digest,
            "format": format_name,
            "validation": {"format": format_name, "status": "passed"},
        }
        if transcript_file is not None:
            metadata["transcript_file"] = transcript_file
        record = SimpleNamespace(
            artifact_id=artifact_id,
            session_id=operation.session_id,
            kind=kind,
            relative_path=relative_path,
            storage_uri=str(storage_path),
            created_at=created_at,
            metadata=metadata,
        )
        self.artifacts.records[artifact_id] = record
        return record


class _FakeEngineRegistry:
    def __init__(self, engine: _FakeExecutionEngine) -> None:
        self.engine = engine

    def require(self, engine_name: str) -> _FakeExecutionEngine:
        assert engine_name == "execution"
        return self.engine


def _execution() -> ControlledOperationExecution:
    return ControlledOperationExecution(
        execution_id="execution_provider",
        operation_id="operation_provider",
        session_id="session_provider",
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        operation_digest="sha256:operation",
        approval_digest="sha256:approval",
        route_policy_id="bio.ncbi_fetch_proteins.provider:v1",
        selected_backend="provider_http",
        adapter_policy_id=durable_adapter_policy_id(
            "bio.ncbi_fetch_proteins.provider:v1"
        ),
        input_identity_digest="sha256:inputs",
        expected_output_contract_digest="sha256:outputs",
        runtime_identity_digest="sha256:runtime",
        lifecycle_state=ControlledOperationExecutionLifecycle.DISPATCHING,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        dispatch_generation=1,
        state_version=3,
        fencing_token=1,
        lease_owner="worker:provider",
        lease_token="lease_provider",
        lease_expires_at="2026-07-21T00:01:00+00:00",
        created_at="2026-07-21T00:00:00+00:00",
        updated_at="2026-07-21T00:00:00+00:00",
    )


def _request(
    execution: ControlledOperationExecution,
) -> ControlledOperationDispatchRequest:
    envelope = {
        "schema_version": "s12.adapter_envelope.v1",
        "adapter_params": {"accessions": ["P12345"]},
    }
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return ControlledOperationDispatchRequest(
        request_id="request_provider",
        execution_id=execution.execution_id,
        operation_id=execution.operation_id,
        session_id=execution.session_id,
        request_digest="sha256:" + hashlib.sha256(encoded).hexdigest(),
        request_envelope=envelope,
        request_size_bytes=len(encoded),
        created_at="2026-07-21T00:00:00+00:00",
    )


def _provider_route_fixture(
    tmp_path: Path,
    *,
    lose_callback: bool = False,
    tamper_observation: bool = False,
    symlink_observation: bool = False,
    observation_extra: dict[str, object] | None = None,
):  # type: ignore[no-untyped-def]
    execution = _execution()
    operation = SimpleNamespace(
        operation_id=execution.operation_id,
        operation_digest=execution.operation_digest,
        session_id=execution.session_id,
        sandbox_run_id="sandbox_run_provider",
        route_policy_id=execution.route_policy_id,
        adapter_envelope_schema_version="s12.adapter_envelope.v1",
    )
    artifacts = _ArtifactRepository()
    repositories = _FakeRepositories(
        controlled_operations=_OperationRepository(operation),
        artifacts=artifacts,
    )
    engine = _FakeExecutionEngine(
        artifacts,
        tmp_path / "provider-artifacts",
        repositories=repositories,
        sandbox_host_call_context_factory=object(),
        lose_callback=lose_callback,
        tamper_observation=tamper_observation,
        symlink_observation=symlink_observation,
        observation_extra=(
            {} if observation_extra is None else dict(observation_extra)
        ),
    )

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    adapter = HostProviderControlledOperationRouteAdapter(
        route_policy_id=execution.route_policy_id,
        repository_scope_factory=repository_scope,
        engine_registry_factory=lambda scoped: _FakeEngineRegistry(engine),
    )
    assert adapter.adapter_policy_id == execution.adapter_policy_id
    request = _request(execution)
    frozen_handle = adapter.prepare_dispatch(execution, request)
    execution = replace(execution, backend_handle_ref=frozen_handle)
    return adapter, execution, request, engine


def test_provider_route_uses_frozen_handle_and_reconciles_without_redispatch(
    tmp_path: Path,
) -> None:
    adapter, execution, request, engine = _provider_route_fixture(tmp_path)
    frozen_handle = execution.backend_handle_ref

    dispatched = adapter.dispatch(execution, request)

    assert dispatched.kind is DurableRouteObservationKind.RESULT_MATERIALIZED
    assert dispatched.backend_handle_ref == frozen_handle
    assert engine.seen_handle == frozen_handle
    assert engine.call_count == 1
    assert dispatched.materialized_result is not None
    envelope = dispatched.materialized_result.bounded_result_envelope
    assert envelope["provider_request_id"] == frozen_handle
    assert envelope["operation_id"] == execution.operation_id
    assert set(envelope["output_artifact_ids"]) == {
        "artifact_provider_request",
        "artifact_provider_fasta",
        "artifact_provider_observation",
    }
    assert envelope["bounded_summary"]["record_count"] == 1
    assert (
        envelope["bounded_summary"]["transcript_manifest"]["provider_request_id"]
        == frozen_handle
    )

    reconciled = adapter.reconcile(execution, request)
    assert reconciled.kind is DurableRouteObservationKind.RESULT_MATERIALIZED
    assert reconciled.backend_handle_ref == frozen_handle
    assert engine.call_count == 1


def test_provider_route_recovers_sealed_summary_after_lost_callback_without_replay(
    tmp_path: Path,
) -> None:
    adapter, execution, request, engine = _provider_route_fixture(
        tmp_path,
        lose_callback=True,
    )

    result = adapter.dispatch(execution, request)

    assert result.kind is DurableRouteObservationKind.RESULT_MATERIALIZED
    assert result.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert engine.call_count == 1
    assert result.materialized_result is not None
    envelope = result.materialized_result.bounded_result_envelope
    summary = envelope["bounded_summary"]
    assert summary["provider"] == "ncbi"
    assert summary["record_count"] == 1
    assert summary["transcript_manifest"]["output_dir"] == (
        "/workspace/output/provider/ncbi"
    )
    assert envelope["validation_results"]["artifact_provider_fasta"] == {
        "format": "fasta",
        "status": "passed",
    }
    ControlledOperationExecutionWorker._validated_result(  # noqa: SLF001
        result.materialized_result
    )


def test_provider_route_fails_closed_when_recovered_transcript_digest_drifts(
    tmp_path: Path,
) -> None:
    adapter, execution, request, engine = _provider_route_fixture(
        tmp_path,
        lose_callback=True,
        tamper_observation=True,
    )

    result = adapter.dispatch(execution, request)

    assert result.kind is DurableRouteObservationKind.TERMINAL_FAILURE
    assert result.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert result.error_code == "durable_provider_transcript_digest_mismatch"
    assert result.materialized_result is None
    assert engine.call_count == 1


def test_provider_route_fails_closed_when_recovered_transcript_is_symlinked(
    tmp_path: Path,
) -> None:
    adapter, execution, request, engine = _provider_route_fixture(
        tmp_path,
        lose_callback=True,
        symlink_observation=True,
    )

    result = adapter.dispatch(execution, request)

    assert result.kind is DurableRouteObservationKind.TERMINAL_FAILURE
    assert result.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert result.error_code == "durable_provider_transcript_unavailable"
    assert result.materialized_result is None
    assert engine.call_count == 1


def test_provider_route_fails_closed_when_recovered_observation_schema_drifts(
    tmp_path: Path,
) -> None:
    adapter, execution, request, engine = _provider_route_fixture(
        tmp_path,
        lose_callback=True,
        observation_extra={"unexpected_recovery_field": True},
    )

    result = adapter.dispatch(execution, request)

    assert result.kind is DurableRouteObservationKind.TERMINAL_FAILURE
    assert result.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert result.error_code == "durable_provider_observation_schema_drift"
    assert result.materialized_result is None
    assert engine.call_count == 1


def test_provider_route_fails_closed_when_recovered_transcript_identity_drifts(
    tmp_path: Path,
) -> None:
    adapter, execution, request, engine = _provider_route_fixture(
        tmp_path,
        lose_callback=True,
        observation_extra={"provider_request_id": "provider_req_drifted"},
    )

    result = adapter.dispatch(execution, request)

    assert result.kind is DurableRouteObservationKind.TERMINAL_FAILURE
    assert result.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert result.error_code == "durable_provider_transcript_identity_drift"
    assert result.materialized_result is None
    assert engine.call_count == 1


def test_provider_route_fails_closed_when_recovered_summary_exceeds_bound(
    tmp_path: Path,
) -> None:
    adapter, execution, request, engine = _provider_route_fixture(
        tmp_path,
        lose_callback=True,
        observation_extra={"summary": {"payload": "x" * (256 * 1024)}},
    )

    result = adapter.dispatch(execution, request)

    assert result.kind is DurableRouteObservationKind.TERMINAL_FAILURE
    assert result.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert result.error_code == "durable_provider_bounded_summary_too_large"
    assert result.materialized_result is None
    assert engine.call_count == 1


def test_provider_route_fails_closed_when_complete_envelope_exceeds_core_bound(
    tmp_path: Path,
) -> None:
    adapter, execution, request, engine = _provider_route_fixture(
        tmp_path,
        lose_callback=True,
        observation_extra={"summary": {"payload": ["sha256:" + "a" * 64] * 3520}},
    )

    result = adapter.dispatch(execution, request)

    assert result.kind is DurableRouteObservationKind.TERMINAL_FAILURE
    assert result.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert result.error_code == "durable_provider_result_envelope_too_large"
    assert result.materialized_result is None
    assert engine.call_count == 1


class _RunRepository:
    def __init__(self) -> None:
        self.records: dict[str, object] = {}

    def list_by_session(self, session_id: str) -> list[object]:
        return [
            record
            for record in self.records.values()
            if record.session_id == session_id  # type: ignore[attr-defined]
        ]


class _EngineDocumentRepository:
    def __init__(self) -> None:
        self.records: dict[str, object] = {}

    def get(self, document_id: str):  # type: ignore[no-untyped-def]
        return self.records.get(document_id)


class _FakeReservedRunner:
    def __init__(self, *, dispatch_in_doubt: bool = False) -> None:
        self.run_id = "runner_reserved_hpc_001"
        self.status = "reserved"
        self.effect_certainty = "no_effect"
        self.retry_eligibility = "same_phase_safe"
        self.reconciliation_required = False
        self.dispatch_in_doubt = dispatch_in_doubt
        self.reserve_count = 0
        self.submit_count = 0
        self.recover_count = 0
        self.toolchain_runtime_identity: object = {
            **_TOOLCHAIN_RUNTIME_IDENTITY,
            "private_sif_path": "/private/tool.sif",
        }

    def reserve_execution(self, identity: dict[str, object]) -> dict[str, str]:
        self.reserve_count += 1
        encoded = json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            "run_id": self.run_id,
            "identity_digest": "sha256:" + hashlib.sha256(encoded).hexdigest(),
        }

    def submit_reserved_execution(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        run_id: str,
    ) -> object:
        del session_id, payload
        assert run_id == self.run_id
        self.submit_count += 1
        if self.submit_count != 1:
            raise AssertionError("reserved runner dispatch was replayed")
        if self.dispatch_in_doubt:
            self.status = "failed"
            self.effect_certainty = "dispatch_in_doubt"
            self.retry_eligibility = "reconcile_required"
            self.reconciliation_required = True
            raise RuntimeError("simulated lost direct SSH dispatch acknowledgement")
        self.status = "completed"
        self.effect_certainty = "terminal_known"
        self.retry_eligibility = "terminal"
        self.reconciliation_required = False
        return self._outcome()

    def inspect_reserved_execution(self, *, run_id: str) -> object:
        assert run_id == self.run_id
        return SimpleNamespace(
            run_id=self.run_id,
            status=self.status,
            execution_mode="ssh",
            phase="dispatching"
            if self.reconciliation_required
            else ("allocated" if self.status == "reserved" else "terminal"),
            effect_certainty=self.effect_certainty,
            retry_eligibility=self.retry_eligibility,
            reconciliation_required=self.reconciliation_required,
            retryable=self.retry_eligibility
            in {"same_phase_safe", "verify_then_retry"},
            runner_attempt_receipt_digest="sha256:" + "b" * 64,
        )

    def recover_reserved_execution_outcome(self, *, run_id: str) -> object:
        assert run_id == self.run_id
        assert self.status in {"completed", "running"}
        self.recover_count += 1
        self.status = "completed"
        self.effect_certainty = "terminal_known"
        self.retry_eligibility = "terminal"
        return self._outcome()

    def _outcome(self) -> object:
        return SimpleNamespace(
            run_id=self.run_id,
            status=RunStatus.SUCCEEDED,
            execution_mode="ssh",
            remote_run_dir=f"opaque://{self.run_id}",
            raw_result={
                "status": "completed",
                "exit_code": 0,
                "runner_attempt_receipt_digest": "sha256:" + "b" * 64,
                "toolchain_runtime_identity": self.toolchain_runtime_identity,
            },
            artifacts=(),
            exit_code=0,
        )


@dataclass
class _FakeHpcExecutionEngine:
    repositories: object
    runner: object
    sandbox_host_call_context_factory: object | None = None
    lose_first_callback: bool = False
    fail_before_submit: bool = False
    fail_fetch: bool = False
    drift_fetch_identity: bool = False
    callback_count: int = 0
    fetch_count: int = 0

    def execute_sandbox_adapter_operation(
        self,
        operation: object,
        envelope: dict[str, object],
    ) -> dict[str, object]:
        self.callback_count += 1
        if self.fail_before_submit:
            raise RuntimeError("simulated Host failure before runner entry")
        run_id = str(envelope["_durable_backend_handle_ref"])
        outcome = self.runner.submit_reserved_execution(  # type: ignore[attr-defined]
            operation.session_id,  # type: ignore[attr-defined]
            {"runspec": {}},
            run_id=run_id,
        )
        if self.lose_first_callback and self.callback_count == 1:
            raise RuntimeError("simulated lost callback after runner terminal")
        local_run_id = f"run_inv_sandbox_adapter_{operation.operation_id}_1"  # type: ignore[attr-defined]
        invocation_id = f"inv_sandbox_adapter_{operation.operation_id}"  # type: ignore[attr-defined]
        self.repositories.runs.records[local_run_id] = SimpleNamespace(  # type: ignore[attr-defined]
            run_id=local_run_id,
            session_id=operation.session_id,  # type: ignore[attr-defined]
            invocation_id=invocation_id,
            approval_id=operation.approval_id,  # type: ignore[attr-defined]
            runner_run_id=run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            summary="bio_tools.mafft placement operation succeeded",
        )
        document_id = (
            "hpc_pending_"
            + hashlib.sha256(local_run_id.encode("utf-8")).hexdigest()[:24]
        )
        pending = {
            "run_id": local_run_id,
            "runner_run_id": run_id,
            "operation_key": "operation_key_mafft",
            "hpc_workspace_id": operation.hpc_workspace_id,  # type: ignore[attr-defined]
            "stage_refs": [
                {
                    "kind": "hpc_stage_ref",
                    "artifact_id": "artifact_input",
                    "artifact_digest": "sha256:" + "c" * 64,
                }
            ],
            "declared_outputs": [
                {"path": "aligned.fasta", "kind": "result", "format": "fasta"}
            ],
            "selected_backend": "hpc",
            "status": RunStatus.SUCCEEDED.value,
            "request_metadata": {
                "catalog_tool_id": "bio_tools.mafft",
                "tool_contract": {
                    "tool_id": "bio_tools.mafft",
                    "adapter_id": "bio_tools.mafft",
                    "command_template_id": "bio_tools_mafft_sif_v1",
                },
            },
            "raw_result": dict(outcome.raw_result),
            "outputs": [
                {
                    "relative_path": "aligned.fasta",
                    "declared_output": {
                        "path": "aligned.fasta",
                        "kind": "result",
                        "format": "fasta",
                    },
                }
            ],
        }
        self.repositories.engine_documents.records[document_id] = SimpleNamespace(  # type: ignore[attr-defined]
            document_id=document_id,
            session_id=operation.session_id,  # type: ignore[attr-defined]
            invocation_id=invocation_id,
            document_kind="hpc_pending_outputs",
            payload=pending,
        )
        run_handle = {
            "kind": "hpc_run_handle",
            "run_id": local_run_id,
            "runner_run_id": run_id,
            "status": RunStatus.SUCCEEDED.value,
        }
        return {
            "adapter_result": {"bounded_summary": run_handle},
            "result_summary": run_handle,
        }

    def fetch_sandbox_hpc_outputs(
        self,
        params: dict[str, object],
    ) -> dict[str, object]:
        self.fetch_count += 1
        if self.fail_fetch:
            raise RuntimeError("simulated Host output fetch interruption")
        artifact_id = "artifact_hpc_result"
        run_id = str(params["run_id"])
        hpc_workspace = dict(params["hpc_workspace"])  # type: ignore[arg-type]
        operation_id = str(params["operation_id"])
        operation_digest = str(params["operation_digest"])
        self.repositories.artifacts.records[artifact_id] = SimpleNamespace(  # type: ignore[attr-defined]
            artifact_id=artifact_id,
            session_id=str(params["session_id"]),
            run_id=run_id,
            kind=ArtifactKind.RESULT,
            relative_path="bio_tools/mafft/aligned.fasta",
            metadata={
                "content_digest": "sha256:" + "d" * 64,
                "controlled_operation_id": (
                    "operation_other" if self.drift_fetch_identity else operation_id
                ),
                "controlled_operation_digest": operation_digest,
                "pipeline_invocation_id": f"inv_sandbox_adapter_{operation_id}",
                "runner_run_id": self.runner.run_id,  # type: ignore[attr-defined]
                "hpc_workspace_id": hpc_workspace["hpc_workspace_id"],
                "declared_output_path": "aligned.fasta",
            },
        )
        return {
            "kind": "hpc_fetch_result",
            "run_id": run_id,
            "hpc_workspace_id": hpc_workspace["hpc_workspace_id"],
            "operation_id": operation_id,
            "operation_digest": operation_digest,
            "registered_artifact_ids": [artifact_id],
            "fetch_refs": [
                {
                    "fetch_ref_id": "fetch_fixture_hpc_result",
                    "declared_output_path": "aligned.fasta",
                    "registered_artifact_id": artifact_id,
                }
            ],
        }


class _FakeHpcEngineRegistry:
    def __init__(self, engine: _FakeHpcExecutionEngine) -> None:
        self.engine = engine

    def require(self, engine_name: str) -> _FakeHpcExecutionEngine:
        assert engine_name == "execution"
        return self.engine


def _hpc_route_fixture(
    *,
    dispatch_in_doubt: bool = False,
    lose_first_callback: bool = False,
    fail_before_submit: bool = False,
    fail_fetch: bool = False,
    drift_fetch_identity: bool = False,
):  # type: ignore[no-untyped-def]
    route_policy_id = "bio_tools.mafft.hpc:v1"
    execution = ControlledOperationExecution(
        execution_id="execution_hpc",
        operation_id="operation_hpc",
        session_id="session_hpc",
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        operation_digest="sha256:" + "1" * 64,
        approval_digest="sha256:" + "2" * 64,
        route_policy_id=route_policy_id,
        selected_backend="hpc",
        adapter_policy_id=durable_adapter_policy_id(route_policy_id),
        input_identity_digest="sha256:" + "3" * 64,
        expected_output_contract_digest="sha256:" + "4" * 64,
        runtime_identity_digest="sha256:" + "5" * 64,
        lifecycle_state=ControlledOperationExecutionLifecycle.DISPATCHING,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        dispatch_generation=1,
        state_version=3,
        fencing_token=1,
        lease_owner="worker:hpc",
        lease_token="lease_hpc",
        lease_expires_at="2026-07-21T00:01:00+00:00",
        approval_id="approval_hpc",
        created_at="2026-07-21T00:00:00+00:00",
        updated_at="2026-07-21T00:00:00+00:00",
    )
    operation = SimpleNamespace(
        operation_id=execution.operation_id,
        operation_digest=execution.operation_digest,
        session_id=execution.session_id,
        approval_id=execution.approval_id,
        route_policy_id=execution.route_policy_id,
        selected_backend="hpc",
        sdk_module="bio_tools",
        function_name="mafft",
        sandbox_workspace_id="sandbox_workspace_hpc_001",
        hpc_workspace_id="hpc_workspace_001",
        runtime_packaging_id="runtime_packaging_001",
        toolchain_id="mafft_toolchain_001",
    )
    repositories = _FakeRepositories(
        controlled_operations=_OperationRepository(operation),
        runs=_RunRepository(),
        engine_documents=_EngineDocumentRepository(),
        artifacts=_ArtifactRepository(),
    )
    runner = _FakeReservedRunner(dispatch_in_doubt=dispatch_in_doubt)
    engine = _FakeHpcExecutionEngine(
        repositories=repositories,
        runner=runner,
        lose_first_callback=lose_first_callback,
        fail_before_submit=fail_before_submit,
        fail_fetch=fail_fetch,
        drift_fetch_identity=drift_fetch_identity,
    )

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    adapter = HostHpcControlledOperationRouteAdapter(
        route_policy_id=route_policy_id,
        repository_scope_factory=repository_scope,
        engine_registry_factory=lambda scoped: _FakeHpcEngineRegistry(engine),
    )
    request_envelope = {
        "schema_version": "s12.adapter_envelope.v1",
        "adapter_params": {},
    }
    encoded = json.dumps(
        request_envelope,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    request = ControlledOperationDispatchRequest(
        request_id="request_hpc",
        execution_id=execution.execution_id,
        operation_id=execution.operation_id,
        session_id=execution.session_id,
        request_digest="sha256:" + hashlib.sha256(encoded).hexdigest(),
        request_envelope=request_envelope,
        request_size_bytes=len(encoded),
        created_at="2026-07-21T00:00:00+00:00",
    )
    handle = adapter.prepare_dispatch(execution, request)
    return (
        adapter,
        replace(execution, backend_handle_ref=handle),
        request,
        runner,
    )


def test_hpc_route_reserves_dispatches_and_materializes_without_handle_leak() -> None:
    adapter, execution, request, runner = _hpc_route_fixture()

    result = adapter.dispatch(execution, request)

    assert result.kind is DurableRouteObservationKind.RESULT_MATERIALIZED
    assert result.materialized_result is not None
    envelope = result.materialized_result.bounded_result_envelope
    assert envelope["kind"] == "hpc_run_handle"
    assert envelope["run_id"].startswith("run_inv_sandbox_adapter_")
    assert envelope["output_artifact_ids"] == ["artifact_hpc_result"]
    assert envelope["toolchain_runtime_identity"] == _TOOLCHAIN_RUNTIME_IDENTITY
    assert [ref.artifact_id for ref in result.materialized_result.artifact_refs] == [
        "artifact_hpc_result"
    ]
    encoded = json.dumps(envelope, sort_keys=True)
    assert runner.run_id not in encoded
    assert "runner_run_id" not in encoded
    assert "/private/tool.sif" not in encoded
    ControlledOperationExecutionWorker._validated_result(  # noqa: SLF001
        result.materialized_result
    )
    assert runner.reserve_count == 1
    assert runner.submit_count == 1

    reconciled = adapter.reconcile(execution, request)
    assert reconciled.kind is DurableRouteObservationKind.RESULT_MATERIALIZED
    assert runner.submit_count == 1


def test_hpc_route_terminalizes_malformed_runner_toolchain_identities() -> None:
    drifted_identities = (
        {**_TOOLCHAIN_RUNTIME_IDENTITY, "adapter_id": 7},
        {
            **_TOOLCHAIN_RUNTIME_IDENTITY,
            "command_template_id": "bio_tools_other_sif_v1",
        },
        {**_TOOLCHAIN_RUNTIME_IDENTITY, "image_digest": "sha256:not-a-digest"},
    )

    for drifted_identity in drifted_identities:
        adapter, execution, request, runner = _hpc_route_fixture()
        runner.toolchain_runtime_identity = drifted_identity

        result = adapter.dispatch(execution, request)

        assert result.kind is DurableRouteObservationKind.TERMINAL_FAILURE
        assert result.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
        assert (
            result.terminal_outcome
            is ControlledOperationExecutionTerminalOutcome.FAILED
        )
        assert result.error_code == "durable_hpc_toolchain_runtime_identity_invalid"
        assert result.materialized_result is None
        assert runner.submit_count == 1


def test_hpc_route_recovers_lost_terminal_callback_without_redispatch() -> None:
    adapter, execution, request, runner = _hpc_route_fixture(lose_first_callback=True)

    result = adapter.dispatch(execution, request)

    assert result.kind is DurableRouteObservationKind.RESULT_MATERIALIZED
    assert runner.submit_count == 1
    assert runner.recover_count == 1


def test_hpc_route_resumes_known_terminal_output_fetch_without_redispatch() -> None:
    adapter, execution, request, runner = _hpc_route_fixture()
    runner.status = "running"
    runner.effect_certainty = "terminal_known"
    runner.retry_eligibility = "verify_then_retry"

    result = adapter.poll(execution, request)

    assert result.kind is DurableRouteObservationKind.RESULT_MATERIALIZED
    assert result.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert runner.submit_count == 0
    assert runner.recover_count == 1


def test_hpc_route_keeps_terminal_certainty_when_output_fetch_is_interrupted() -> None:
    adapter, execution, request, runner = _hpc_route_fixture(fail_fetch=True)

    result = adapter.dispatch(execution, request)
    reconciled = adapter.reconcile(execution, request)

    assert result.kind is DurableRouteObservationKind.RESULT_PENDING
    assert result.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert reconciled.kind is DurableRouteObservationKind.RESULT_PENDING
    assert reconciled.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert runner.submit_count == 1


def test_hpc_route_does_not_publish_an_identity_drifted_artifact_set() -> None:
    adapter, execution, request, runner = _hpc_route_fixture(drift_fetch_identity=True)

    result = adapter.dispatch(execution, request)

    assert result.kind is DurableRouteObservationKind.RESULT_PENDING
    assert result.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert result.materialized_result is None
    assert result.error_code == "durable_hpc_artifact_set_validation_pending"
    assert runner.submit_count == 1


def test_hpc_route_preserves_direct_ssh_dispatch_ambiguity() -> None:
    adapter, execution, request, runner = _hpc_route_fixture(dispatch_in_doubt=True)

    result = adapter.dispatch(execution, request)
    reconciled = adapter.reconcile(execution, request)

    assert result.kind is DurableRouteObservationKind.RECONCILE_REQUIRED
    assert result.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert reconciled.kind is DurableRouteObservationKind.RECONCILE_REQUIRED
    assert runner.submit_count == 1
    assert runner.recover_count == 0


def test_hpc_route_bounds_host_pre_effect_recovery_on_same_handle() -> None:
    adapter, execution, request, runner = _hpc_route_fixture(fail_before_submit=True)

    first = adapter.dispatch(execution, request)
    second_execution = replace(execution, dispatch_generation=2)
    second_handle = adapter.prepare_dispatch(second_execution, request)
    second = adapter.dispatch(second_execution, request)

    assert first.kind is DurableRouteObservationKind.PROVEN_NO_EFFECT
    assert second_handle == execution.backend_handle_ref
    assert second.kind is DurableRouteObservationKind.TERMINAL_FAILURE
    assert second.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert runner.submit_count == 0
