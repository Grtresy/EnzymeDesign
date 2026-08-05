from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import threading
from typing import Any

from openzyme_core import ControlledOperationExecutionWorker
from openzyme_core import DurableRouteMaterializedResult
from openzyme_core import SandboxRuntimeError
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_core import sandbox_runtime as core_sandbox_runtime
from openzyme_domain import ArtifactKind
from openzyme_domain import MutationWriterKind
from openzyme_engines import podman_sandbox as engine_sandbox_runtime
from openzyme_engines.execution import PipelineSdkFailure
from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_pipeline import artifacts as pipeline_artifacts
from openzyme_pipeline import client as pipeline_client
from openzyme_runtime import ArtifactBoundaryError
from openzyme_runtime import ArtifactBoundaryService

from .composition import ProductionComposition
from .driver import AdmittedOperation
from .driver import QualificationDriver
from .external_ports import ExternalEffectLedger
from .fault_process import IdentityBoundFaultProcessRunner
from .safety import QualificationSafetyGuard


CASE_NAMES = ("limit_minus_one", "limit", "limit_plus_one")


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def exact_scalar_document(size_bytes: int, *, marker: str = "") -> dict[str, object]:
    payload: dict[str, object] = {"padding": marker}
    base_size = len(canonical_json_bytes(payload))
    if base_size > size_bytes:
        raise ValueError("target boundary is too small for the scalar document")
    payload["padding"] = marker + "x" * (size_bytes - base_size)
    if len(canonical_json_bytes(payload)) != size_bytes:
        raise AssertionError("scalar boundary document size drifted")
    return payload


def exact_chunked_document(size_bytes: int) -> dict[str, object]:
    payload: dict[str, object] = {"padding": []}
    values = payload["padding"]
    assert isinstance(values, list)
    while True:
        current = len(canonical_json_bytes(payload))
        remaining = size_bytes - current
        if remaining <= 0:
            break
        overhead = 2 if not values else 3
        if remaining <= overhead:
            if not values:
                raise ValueError("target boundary is too small for chunked JSON")
            values[-1] = str(values[-1]) + "x" * remaining
            break
        values.append("x" * min(512, remaining - overhead))
    if len(canonical_json_bytes(payload)) != size_bytes:
        raise AssertionError("chunked boundary document size drifted")
    return payload


@dataclass(frozen=True, slots=True)
class ArtifactMetadataBoundaryProbe:
    inline_outcomes: dict[str, dict[str, str]]
    sidecar_outcomes: dict[str, dict[str, str]]
    sidecar_minus_one: dict[str, object]
    sidecar_equal: dict[str, object]
    workspace_path: Path


@dataclass(frozen=True, slots=True)
class PublicDiagnosticScaleProbe:
    completed_within_deadline: bool
    deadline_milliseconds: int
    effect_ledger: dict[str, object]
    evidence_digest: str
    input_byte_length: int
    raw_exit_code: int | None
    retirement_proven: bool


def _transport_kind(transport: dict[str, Any]) -> str:
    if set(transport) == {"metadata"}:
        return "inline"
    if set(transport) == {"metadata_sidecar"}:
        return "sidecar"
    raise AssertionError("pipeline metadata transport is not closed")


def probe_artifact_metadata_boundaries(
    composition: ProductionComposition,
    *,
    ids: AdmittedOperation,
    inline_cases: tuple[int, int, int],
    sidecar_cases: tuple[int, int, int],
) -> ArtifactMetadataBoundaryProbe:
    workspace_path = composition.roots.sandbox_root / ids.sandbox_workspace_id
    for name in ("input", "output", "work"):
        (workspace_path / name).mkdir(parents=True, exist_ok=True)
    engine_server = engine_sandbox_runtime._ControlSocketServer(  # noqa: SLF001
        socket_path=workspace_path / "engine-boundary.sock",
        input_dir=workspace_path / "input",
        output_dir=workspace_path / "output",
        artifacts={},
    )
    original_work_root = pipeline_artifacts.ARTIFACT_REGISTRATION_METADATA_WORK_ROOT
    pipeline_artifacts.ARTIFACT_REGISTRATION_METADATA_WORK_ROOT = (
        workspace_path / "work"
    )
    inline_outcomes: dict[str, dict[str, str]] = {}
    sidecar_outcomes: dict[str, dict[str, str]] = {}
    sidecar_descriptors: dict[str, dict[str, object]] = {}
    try:
        with composition.dependencies.v3_repository_scope(
            mode="read"
        ) as repositories:
            service = ArtifactBoundaryService(
                repositories,
                workspace_root=composition.roots.sandbox_root,
                blob_store_root=composition.roots.blob_root,
            )
            for case_name, target in zip(CASE_NAMES, inline_cases, strict=True):
                metadata = exact_scalar_document(target, marker=f"inline-{case_name}:")
                transport = pipeline_artifacts._metadata_transport(metadata)  # noqa: SLF001
                outcome = {"pipeline": _transport_kind(transport)}
                try:
                    resolved = service.resolve_registration_metadata(
                        session_id=ids.session_id,
                        sandbox_workspace_id=ids.sandbox_workspace_id,
                        metadata=metadata,
                    )
                except ArtifactBoundaryError as exc:
                    outcome["host"] = f"rejected:{exc.error_code}"
                else:
                    assert len(canonical_json_bytes(resolved)) == target
                    outcome["host"] = "accepted"
                try:
                    engine_resolved = engine_server._registration_metadata(  # noqa: SLF001
                        {"metadata": metadata}
                    )
                except (ArtifactBoundaryError, ValueError) as exc:
                    outcome["engine"] = f"rejected:{type(exc).__name__}"
                else:
                    assert len(canonical_json_bytes(engine_resolved)) == target
                    outcome["engine"] = "accepted"
                if case_name == "limit_plus_one":
                    descriptor = transport.get("metadata_sidecar")
                    assert isinstance(descriptor, dict)
                    resolved_sidecar = service.resolve_registration_metadata(
                        session_id=ids.session_id,
                        sandbox_workspace_id=ids.sandbox_workspace_id,
                        metadata_sidecar=descriptor,
                    )
                    assert len(canonical_json_bytes(resolved_sidecar)) == target
                    outcome["host_sidecar"] = "accepted"
                inline_outcomes[case_name] = outcome

            for case_name, target in zip(CASE_NAMES, sidecar_cases, strict=True):
                metadata = exact_scalar_document(
                    target,
                    marker=f"sidecar-{case_name}:",
                )
                outcome: dict[str, str] = {}
                try:
                    transport = pipeline_artifacts._metadata_transport(metadata)  # noqa: SLF001
                except pipeline_client.PipelineSdkError as exc:
                    outcome["pipeline"] = f"rejected:{exc.error_code}"
                    descriptor = dict(sidecar_descriptors["limit"])
                    descriptor["size_bytes"] = target
                else:
                    outcome["pipeline"] = _transport_kind(transport)
                    raw_descriptor = transport.get("metadata_sidecar")
                    assert isinstance(raw_descriptor, dict)
                    descriptor = dict(raw_descriptor)
                    sidecar_descriptors[case_name] = descriptor
                try:
                    resolved = service.resolve_registration_metadata(
                        session_id=ids.session_id,
                        sandbox_workspace_id=ids.sandbox_workspace_id,
                        metadata_sidecar=descriptor,
                    )
                except ArtifactBoundaryError as exc:
                    outcome["host"] = f"rejected:{exc.error_code}"
                else:
                    assert len(canonical_json_bytes(resolved)) == target
                    outcome["host"] = "accepted"
                try:
                    engine_resolved = engine_server._registration_metadata(  # noqa: SLF001
                        {"metadata_sidecar": descriptor}
                    )
                except (ArtifactBoundaryError, ValueError) as exc:
                    code = getattr(exc, "error_code", type(exc).__name__)
                    outcome["engine"] = f"rejected:{code}"
                else:
                    assert len(canonical_json_bytes(engine_resolved)) == target
                    outcome["engine"] = "accepted"
                sidecar_outcomes[case_name] = outcome
    finally:
        pipeline_artifacts.ARTIFACT_REGISTRATION_METADATA_WORK_ROOT = (
            original_work_root
        )
    return ArtifactMetadataBoundaryProbe(
        inline_outcomes=inline_outcomes,
        sidecar_outcomes=sidecar_outcomes,
        sidecar_minus_one=sidecar_descriptors["limit_minus_one"],
        sidecar_equal=sidecar_descriptors["limit"],
        workspace_path=workspace_path,
    )


def probe_register_many_aggregate_boundary(
    composition: ProductionComposition,
    *,
    ids: AdmittedOperation,
    cases: tuple[int, int, int],
    metadata_probe: ArtifactMetadataBoundaryProbe,
) -> dict[str, dict[str, str]]:
    if int(metadata_probe.sidecar_minus_one["size_bytes"]) != cases[0]:
        raise AssertionError("aggregate minus-one case lost sidecar identity")
    if int(metadata_probe.sidecar_equal["size_bytes"]) != cases[1]:
        raise AssertionError("aggregate equal case lost sidecar identity")
    item = {"path": "/workspace/output/missing-boundary.csv"}
    case_items = {
        "limit_minus_one": [
            {**item, "metadata_sidecar": metadata_probe.sidecar_minus_one}
        ],
        "limit": [{**item, "metadata_sidecar": metadata_probe.sidecar_equal}],
        "limit_plus_one": [
            {**item, "metadata_sidecar": metadata_probe.sidecar_minus_one},
            {**item, "metadata": {}},
        ],
    }
    records = QualificationDriver(composition).canonical_records(ids)
    operation = records["operation"]
    assert isinstance(operation, dict)
    source_snapshot_id = str(operation["source_snapshot_artifact_id"])
    source_snapshot_digest = str(operation["source_snapshot_digest"])
    outcomes: dict[str, dict[str, str]] = {}
    for case_name in CASE_NAMES:
        items = case_items[case_name]
        request = {
            "id": f"core-{case_name}",
            "jsonrpc": "2.0",
            "method": "artifacts.register_many",
            "params": {"items": items},
        }
        with composition.dependencies.v3_mutation_writer_scope(
            session_id=ids.session_id,
            owner_kind=MutationWriterKind.ARTIFACT_PUBLISHER,
            owner_ref=f"qualification-boundary-register-many:{case_name}",
        ):
            with composition.dependencies.v3_repository_scope(
                mode="connection"
            ) as repositories:
                core_server = core_sandbox_runtime._ControlSocketServer(  # noqa: SLF001
                    socket_path=metadata_probe.workspace_path
                    / f"core-{case_name}.sock",
                    repositories=repositories,
                    session_id=ids.session_id,
                    sandbox_workspace_id=ids.sandbox_workspace_id,
                    sandbox_run_id=ids.sandbox_run_id,
                    agent_id="agent:master",
                    source_snapshot_artifact_id=source_snapshot_id,
                    source_tree_digest=source_snapshot_digest,
                    workspace_root=composition.roots.sandbox_root,
                    artifact_blob_root=composition.roots.blob_root,
                )
                try:
                    core_server._handle_artifact_boundary(  # noqa: SLF001
                        request,
                        "artifacts.register_many",
                        {"items": items},
                    )
                except SandboxRuntimeError as exc:
                    prefix = (
                        "rejected"
                        if exc.error_code
                        == "artifact_register_many_metadata_too_large"
                        else "downstream"
                    )
                    core_outcome = f"{prefix}:{exc.error_code}"
                else:
                    core_outcome = "accepted"
        engine_server = engine_sandbox_runtime._ControlSocketServer(  # noqa: SLF001
            socket_path=metadata_probe.workspace_path
            / f"engine-{case_name}.sock",
            input_dir=metadata_probe.workspace_path / "input",
            output_dir=metadata_probe.workspace_path / "output",
            artifacts={},
        )
        engine_response = engine_server._handle(request)  # noqa: SLF001
        if "error" in engine_response:
            message = str(engine_response["error"]["message"])
            prefix = (
                "rejected"
                if "aggregate limit" in message
                else "downstream"
            )
            engine_outcome = f"{prefix}:{message}"
        else:
            engine_outcome = "accepted"
        outcomes[case_name] = {
            "core": core_outcome,
            "engine": engine_outcome,
        }
    return outcomes


def probe_dispatch_request_boundary(
    driver: QualificationDriver,
    *,
    session_id_prefix: str,
    cases: tuple[int, int, int],
) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for case_name, target in zip(CASE_NAMES, cases, strict=True):
        session_id = f"{session_id_prefix}_{case_name}"
        driver.create_session(session_id)
        envelope = exact_scalar_document(target, marker=f"dispatch-{case_name}:")
        try:
            driver.admit_durable_operation(
                session_id=session_id,
                scenario_key=f"boundary_dispatch_{case_name}",
                route_policy_id="qualification.provider:v1",
                selected_backend="qualification_provider",
                adapter_policy_id="qualification_provider_adapter:v1",
                request_envelope=envelope,
            )
        except ValueError as exc:
            outcomes[case_name] = f"rejected:{exc}"
        else:
            outcomes[case_name] = "accepted"
    return outcomes


def _provider_adapter(composition: ProductionComposition) -> Any:
    wrapper = composition.dependencies.v3_durable_route_adapters[
        "bio.ncbi_fetch_proteins.provider:v1"
    ]
    adapter = getattr(wrapper, "inner", wrapper)
    if not hasattr(adapter, "_read_verified_provider_document"):
        raise RuntimeError("production provider route lost its transcript reader")
    return adapter


def probe_durable_result_and_provider_summary_boundaries(
    composition: ProductionComposition,
    *,
    cases: tuple[int, int, int],
) -> dict[str, dict[str, str]]:
    adapter = _provider_adapter(composition)
    digest = "sha256:" + "a" * 64
    record = SimpleNamespace(
        artifact_id="artifact_boundary_result",
        kind=ArtifactKind.RESULT,
        relative_path="provider_parsed/boundary.json",
        metadata={"content_digest": digest, "sealed_digest": digest},
    )
    execution = SimpleNamespace(
        operation_id="op_boundary_result",
        operation_digest="sha256:" + "b" * 64,
        backend_handle_ref="provider_req_boundary_result",
    )
    operation = SimpleNamespace(
        operation_id=execution.operation_id,
        operation_digest=execution.operation_digest,
        sandbox_run_id="srun_boundary_result",
        adapter_envelope_schema_version="s12.adapter_envelope.v1",
    )
    adapter_result = {
        "bounded_summary": {},
        "output_artifact_ids": [record.artifact_id],
        "provider_request_id": execution.backend_handle_ref,
        "registered_artifact_ids": [record.artifact_id],
        "safe_diagnostics_ref": "artifact://boundary/provider_observation.json",
        "status": "succeeded",
        "validation_results": {record.artifact_id: {}},
        "warnings": [],
    }
    outcomes: dict[str, dict[str, str]] = {}
    for case_name, target in zip(CASE_NAMES, cases, strict=True):
        envelope = exact_chunked_document(target)
        result = DurableRouteMaterializedResult(
            bounded_result_envelope=envelope,
            artifact_set_digest=controlled_operation_artifact_set_digest(()),
            origin="qualification_boundary_probe",
        )
        try:
            ControlledOperationExecutionWorker._validated_result(result)  # noqa: SLF001
        except ValueError as exc:
            worker_outcome = f"rejected:{exc}"
        else:
            worker_outcome = "accepted"
        summary_adapter_result = dict(adapter_result)
        summary_adapter_result["bounded_summary"] = envelope
        try:
            adapter._materialized_from_records(  # noqa: SLF001
                execution=execution,
                operation=operation,
                records=(record,),
                bounded_summary=envelope,
                adapter_result=summary_adapter_result,
            )
        except PipelineSdkFailure as exc:
            summary_outcome = f"rejected:{exc.error_type}"
        else:
            summary_outcome = "accepted"
        outcomes[case_name] = {
            "provider_summary": summary_outcome,
            "worker": worker_outcome,
        }
    return outcomes


def probe_provider_document_boundary(
    composition: ProductionComposition,
    *,
    root: Path,
    cases: tuple[int, int, int],
) -> dict[str, str]:
    adapter = _provider_adapter(composition)
    root.mkdir(parents=True, exist_ok=True)
    outcomes: dict[str, str] = {}
    for case_name, target in zip(CASE_NAMES, cases, strict=True):
        content = canonical_json_bytes(
            exact_scalar_document(target, marker=f"document-{case_name}:")
        )
        path = root / f"{case_name}.json"
        path.write_bytes(content)
        record = SimpleNamespace(
            storage_uri=str(path),
            metadata={
                "content_digest": _sha256(content),
                "sealed_digest": _sha256(content),
            },
        )
        try:
            parsed = adapter._read_verified_provider_document(  # noqa: SLF001
                record,
                document_name="boundary document",
            )
        except PipelineSdkFailure as exc:
            outcomes[case_name] = f"rejected:{exc.error_type}"
        else:
            assert len(canonical_json_bytes(parsed)) == target
            outcomes[case_name] = "accepted"
        path.unlink()
    return outcomes


def _frame_read_outcome(
    reader: Any,
    *,
    payload: bytes,
) -> str:
    receiver, sender = socket.socketpair()

    def send() -> None:
        try:
            sender.sendall(payload + b"\n")
        except OSError:
            pass
        finally:
            sender.close()

    thread = threading.Thread(target=send, daemon=False)
    thread.start()
    try:
        received = reader(receiver)
    except Exception as exc:  # noqa: BLE001 - classify both server implementations
        outcome = f"rejected:{getattr(exc, 'error_code', type(exc).__name__)}"
    else:
        assert received == payload
        outcome = "accepted"
    finally:
        receiver.close()
        thread.join(timeout=2.0)
    if thread.is_alive():
        raise RuntimeError("boundary frame sender did not retire")
    return outcome


def _pipeline_params_for_size(size_bytes: int) -> dict[str, object]:
    sample = {
        "id": "rpc_000000000000",
        "jsonrpc": "2.0",
        "method": "s09.transport_smoke",
        "params": {"padding": ""},
    }
    base_size = len(json.dumps(sample, sort_keys=True).encode("utf-8"))
    if base_size > size_bytes:
        raise ValueError("pipeline control target is too small")
    params = {"padding": "x" * (size_bytes - base_size)}
    sample["params"] = params
    if len(json.dumps(sample, sort_keys=True).encode("utf-8")) != size_bytes:
        raise AssertionError("pipeline request frame size drifted")
    return params


def _pipeline_roundtrip(socket_path: Path, *, params: dict[str, object]) -> object:
    ready = threading.Event()
    failure: list[BaseException] = []

    def serve() -> None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(socket_path))
                server.listen(1)
                ready.set()
                connection, _ = server.accept()
                with connection:
                    content = bytearray()
                    while not content.endswith(b"\n"):
                        chunk = connection.recv(64 * 1024)
                        if not chunk:
                            raise RuntimeError("pipeline boundary request was truncated")
                        content.extend(chunk)
                    request = json.loads(content[:-1])
                    response = {
                        "id": request["id"],
                        "jsonrpc": "2.0",
                        "result": {"status": "accepted"},
                    }
                    connection.sendall(
                        json.dumps(response, sort_keys=True).encode("utf-8") + b"\n"
                    )
        except BaseException as exc:  # noqa: BLE001 - surfaced in caller
            failure.append(exc)
            ready.set()

    thread = threading.Thread(target=serve, daemon=False)
    thread.start()
    if not ready.wait(timeout=2.0):
        raise RuntimeError("pipeline boundary server did not start")
    result = pipeline_client.ControlClient(socket_path=str(socket_path)).call(
        "s09.transport_smoke",
        params,
    )
    thread.join(timeout=2.0)
    if thread.is_alive():
        raise RuntimeError("pipeline boundary server did not retire")
    if failure:
        raise RuntimeError("pipeline boundary server failed") from failure[0]
    return result


def probe_control_frame_boundary(
    *,
    root: Path,
    cases: tuple[int, int, int],
) -> dict[str, dict[str, str]]:
    root.mkdir(parents=True, exist_ok=True)
    outcomes: dict[str, dict[str, str]] = {}
    with tempfile.TemporaryDirectory(prefix="ozq-control-", dir="/tmp") as short:
        socket_root = Path(short)
        for case_name, target in zip(CASE_NAMES, cases, strict=True):
            payload = canonical_json_bytes(
                exact_scalar_document(target, marker=f"frame-{case_name}:")
            )
            core_outcome = _frame_read_outcome(
                core_sandbox_runtime._ControlSocketServer._read_request_frame,  # noqa: SLF001
                payload=payload,
            )
            engine_outcome = _frame_read_outcome(
                engine_sandbox_runtime._ControlSocketServer._read_frame,  # noqa: SLF001
                payload=payload,
            )
            params = _pipeline_params_for_size(target)
            if case_name == "limit_plus_one":
                try:
                    pipeline_client.ControlClient(
                        socket_path=str(socket_root / "absent.sock")
                    ).call("s09.transport_smoke", params)
                except pipeline_client.PipelineSdkError as exc:
                    pipeline_outcome = f"rejected:{exc.error_code}"
                else:
                    pipeline_outcome = "accepted"
            else:
                result = _pipeline_roundtrip(
                    socket_root / f"{case_name}.sock",
                    params=params,
                )
                assert result == {"status": "accepted"}
                pipeline_outcome = "accepted"
            outcomes[case_name] = {
                "core": core_outcome,
                "engine": engine_outcome,
                "pipeline": pipeline_outcome,
            }
    return outcomes


def probe_public_diagnostic_bounded_work(
    *,
    registry: Mapping[str, object],
    deadline_seconds: float = 1.5,
) -> PublicDiagnosticScaleProbe:
    if deadline_seconds <= 0:
        raise ValueError("sanitizer scale deadline must be positive")
    ledger = ExternalEffectLedger()
    with QualificationSafetyGuard(registry=registry) as guard:
        runner = IdentityBoundFaultProcessRunner(
            registry=registry,
            ledger=ledger,
            safety_guard=guard,
            readiness_timeout_seconds=10.0,
            operator_grace_seconds=2.0,
            term_grace_seconds=2.0,
            kill_grace_seconds=5.0,
            deadline_seconds=2.0,
        )
        handle = runner.start("sanitize_long_scalar")
        try:
            handle.process.wait(timeout=deadline_seconds)
        except subprocess.TimeoutExpired:
            completed = False
        else:
            completed = handle.process.returncode == 0
        retirement = handle.retire(operator_signal=None)
    input_byte_length = int(handle.ready_payload["input_byte_length"])
    effect_ledger = ledger.snapshot()
    evidence_payload = {
        "completed_within_deadline": completed,
        "deadline_milliseconds": round(deadline_seconds * 1000),
        "effect_ledger_digest": effect_ledger["ledger_digest"],
        "input_byte_length": input_byte_length,
        "raw_exit_code": retirement.payload["raw_exit_code"],
        "retirement_evidence_digest": retirement.evidence_digest,
        "retirement_proven": retirement.payload["retirement_proven"],
        "schema_id": "openzyme_v3_public_diagnostic_scale_probe@1",
    }
    return PublicDiagnosticScaleProbe(
        completed_within_deadline=completed,
        deadline_milliseconds=round(deadline_seconds * 1000),
        effect_ledger=effect_ledger,
        evidence_digest=_sha256(canonical_json_bytes(evidence_payload)),
        input_byte_length=input_byte_length,
        raw_exit_code=retirement.payload["raw_exit_code"],  # type: ignore[arg-type]
        retirement_proven=bool(retirement.payload["retirement_proven"]),
    )


__all__ = [
    "ArtifactMetadataBoundaryProbe",
    "CASE_NAMES",
    "PublicDiagnosticScaleProbe",
    "exact_chunked_document",
    "exact_scalar_document",
    "probe_artifact_metadata_boundaries",
    "probe_control_frame_boundary",
    "probe_dispatch_request_boundary",
    "probe_durable_result_and_provider_summary_boundaries",
    "probe_provider_document_boundary",
    "probe_public_diagnostic_bounded_work",
    "probe_register_many_aggregate_boundary",
]
