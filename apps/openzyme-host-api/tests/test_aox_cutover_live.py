from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import struct
import threading
import time
from types import SimpleNamespace
import zlib

from fastapi import FastAPI
import httpx
import pytest

from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionReportDraftRecord
from openzyme_domain import SessionReportDraftStatus
from openzyme_domain import SessionReportRecord
from openzyme_domain import SessionReportStatus
from openzyme_core import DurableEventRecord
from openzyme_core import EngineDocumentRecord
from openzyme_core import SQLiteRepositoryProvider
from openzyme_host_api import aox_cutover_live as live
from openzyme_host_api.aox_cutover_cli import build_parser
from openzyme_host_api.aox_cutover_evidence import AttemptRunContext
from openzyme_host_api.aox_cutover_evidence import build_attempt_bundle
from openzyme_host_api.aox_cutover_evidence import controlled_operation_digest
from openzyme_host_api.aox_cutover_evidence import create_blank_world_roots
from openzyme_host_api.aox_cutover_evidence import safe_micu_ledger_snapshot
from openzyme_host_api.aox_cutover_evidence import seal_attempt_bundle
from openzyme_host_api.aox_cutover_evidence import verify_attempt_bundle
from openzyme_host_api.aox_cutover_evidence import _report_publish_receipt_is_valid
from openzyme_pipeline import aox_motif
from openzyme_pipeline import aox_reference
from openzyme_runtime import OpenZymeSettings
from openzyme_host_api import aox_cutover_evidence as cutover_evidence


def _digest(label: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _chrome_effective_config() -> dict[str, object]:
    return {"driver": {"ui_dist_digest": _digest("built-ui-dist")}}


def _public_receipt(
    *,
    sequence: int,
    route: str,
    semantic_value: object,
) -> live.PublicApiReceipt:
    return live.PublicApiReceipt(
        sequence=sequence,
        method="GET",
        route=route,
        status_code=200,
        request_digest=_digest(f"request:{sequence}:{route}"),
        response_digest=_digest(f"response:{sequence}:{route}"),
        response_semantic_digest=live.canonical_digest(semantic_value),
    )


class _ReceiptAwareFake:
    """Small fake-side mirror of the driver's thread-local receipt contract."""

    def __init__(
        self,
        initial_receipts: tuple[live.PublicApiReceipt, ...] = (),
    ) -> None:
        self._receipt_lock = threading.Lock()
        self._receipts = list(initial_receipts)
        self._thread_state = threading.local()
        if initial_receipts:
            self._thread_state.last_receipt = initial_receipts[-1]

    @property
    def receipts(self) -> tuple[live.PublicApiReceipt, ...]:
        with self._receipt_lock:
            return tuple(self._receipts)

    @property
    def last_receipt(self) -> live.PublicApiReceipt:
        receipt = getattr(self._thread_state, "last_receipt", None)
        if not isinstance(receipt, live.PublicApiReceipt):
            raise live.LiveProductPathError(
                "public_api_response_receipt_missing",
                "current fake API thread has no response receipt",
            )
        return receipt

    def _append_receipt(self, receipt: live.PublicApiReceipt) -> None:
        with self._receipt_lock:
            self._receipts.append(receipt)
        self._thread_state.last_receipt = receipt


class _JsonResponse:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def json(self) -> object:
        return self._payload


class _OutOfOrderJsonClient:
    base_url = "http://127.0.0.1:54321"

    def __init__(self) -> None:
        self.routes = (
            "/v3/sessions/sess_receipt_first/workspace",
            "/v3/sessions/sess_receipt_second/workspace",
        )
        self.started = {route: threading.Event() for route in self.routes}
        self.release = {route: threading.Event() for route in self.routes}

    def get(self, route: str) -> _JsonResponse:
        assert route in self.started
        self.started[route].set()
        if not self.release[route].wait(timeout=2.0):
            raise AssertionError(f"test did not release {route}")
        return _JsonResponse({"route": route})


class _SerialApprovalJsonClient:
    base_url = "http://127.0.0.1:54321"

    def __init__(self, approval_ids: tuple[str, ...]) -> None:
        self.approval_ids = approval_ids
        self._condition = threading.Condition()
        self._current_index: int | None = None
        self._force_release = False
        self._drain_inflight = False
        self.drain_started = threading.Event()
        self.resolve_calls: list[tuple[str, str, bool]] = []
        self.call_order: list[str] = []

    def get(self, route: str) -> _JsonResponse:
        assert route == "/v3/sessions/sess_serial/workspace"
        with self._condition:
            ready = self._condition.wait_for(
                lambda: self._current_index is not None or self._force_release,
                timeout=2.0,
            )
            if not ready:
                raise AssertionError("blocking drain never exposed its first approval")
            pending: list[dict[str, object]] = []
            if (
                not self._force_release
                and self._current_index is not None
                and self._current_index < len(self.approval_ids)
            ):
                pending = [
                    {"approval_id": self.approval_ids[self._current_index]}
                ]
        return _JsonResponse({"pending_approvals": pending})

    def post(
        self,
        route: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _JsonResponse:
        del headers
        if route == "/v3/sessions/sess_serial/runtime/drain":
            with self._condition:
                self._current_index = 0
                self._drain_inflight = True
                self.drain_started.set()
                self._condition.notify_all()
                finished = self._condition.wait_for(
                    lambda: self._force_release
                    or (
                        self._current_index is not None
                        and self._current_index >= len(self.approval_ids)
                    ),
                    timeout=2.0,
                )
                self._drain_inflight = False
                if not finished:
                    raise AssertionError("serial approvals were not resolved")
            return _JsonResponse({"status": "completed"})

        prefix = "/v3/approvals/"
        suffix = "/resolve"
        assert route.startswith(prefix) and route.endswith(suffix)
        approval_id = route[len(prefix) : -len(suffix)]
        decision = str(json.get("decision") or "")
        with self._condition:
            assert self._current_index is not None
            assert self._current_index < len(self.approval_ids)
            assert approval_id == self.approval_ids[self._current_index]
            self.call_order.append(f"resolve:{approval_id}:{decision}")
            self.resolve_calls.append(
                (approval_id, decision, self._drain_inflight)
            )
            self._current_index += 1
            if decision != "approved":
                self._force_release = True
            self._condition.notify_all()
        return _JsonResponse(
            {"approval_id": approval_id, "decision": decision}
        )

    def release_all(self) -> None:
        with self._condition:
            self._force_release = True
            self._condition.notify_all()


class _FailingDrainJsonClient:
    base_url = "http://127.0.0.1:54321"

    def post(
        self,
        route: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _JsonResponse:
        del json, headers
        assert route == "/v3/sessions/sess_failed/runtime/drain"
        raise RuntimeError("private background failure detail")


class _ConcurrentDrainAndWorkspaceFailureJsonClient:
    """Synchronize a workspace failure behind a failed drain unwind."""

    base_url = "http://127.0.0.1:54321"

    def __init__(self, *, drain_thread_name: str) -> None:
        self.drain_thread_name = drain_thread_name
        self.workspace_get_started = threading.Event()
        self.drain_failure_started = threading.Event()

    def get(self, route: str) -> _JsonResponse:
        assert route == "/v3/sessions/sess_concurrent_failure/workspace"
        self.workspace_get_started.set()
        assert self.drain_failure_started.wait(timeout=2.0)
        drain_thread = next(
            (
                thread
                for thread in threading.enumerate()
                if thread.name == self.drain_thread_name
            ),
            None,
        )
        assert drain_thread is not None
        drain_thread.join(timeout=2.0)
        assert not drain_thread.is_alive()
        raise RuntimeError("private workspace failure detail")

    def post(
        self,
        route: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _JsonResponse:
        del json, headers
        assert route == (
            "/v3/sessions/sess_concurrent_failure/runtime/drain"
        )
        assert self.workspace_get_started.wait(timeout=2.0)
        self.drain_failure_started.set()
        raise RuntimeError("private concurrent drain failure detail")


class _DrainReturnsPendingApprovalJsonClient:
    """Expose an approval in the same bounded response that yields for it."""

    base_url = "http://127.0.0.1:54321"

    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        self.pending = False
        self.drain_returned = threading.Event()
        self.resolve_calls: list[tuple[str, str, bool]] = []

    def get(self, route: str) -> _JsonResponse:
        assert route == "/v3/sessions/sess_post_response/workspace"
        return _JsonResponse(
            {
                "pending_approvals": (
                    [{"approval_id": self.approval_id}] if self.pending else []
                )
            }
        )

    def post(
        self,
        route: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _JsonResponse:
        del headers
        if route == "/v3/sessions/sess_post_response/runtime/drain":
            self.pending = True
            self.drain_returned.set()
            return _JsonResponse({"status": "waiting_approval"})

        expected_route = f"/v3/approvals/{self.approval_id}/resolve"
        assert route == expected_route
        decision = str(json.get("decision") or "")
        self.resolve_calls.append(
            (self.approval_id, decision, self.drain_returned.is_set())
        )
        self.pending = False
        return _JsonResponse(
            {"approval_id": self.approval_id, "decision": decision}
        )


def _one_pixel_grayscale_png(
    *,
    filter_byte: int,
    trailing_zlib_bytes: bytes = b"",
) -> str:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    idat = zlib.compress(bytes((filter_byte, 0))) + trailing_zlib_bytes
    content = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(content).decode("ascii")


def _identity() -> dict[str, str]:
    return {
        "git_commit": "a" * 40,
        "config_digest": _digest("config"),
        "workflow_ref": f"workflow:aox-hmm-live@2.0.0#{_digest('workflow')}",
        "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
        "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
        "image_digest": _digest("image"),
        "sdk_digest": _digest("sdk"),
    }


def _allowed_prerequisites() -> dict[str, object]:
    identity = _identity()
    hmmer_digest = _digest("hmmer-sif")
    return {
        "git_commit": identity["git_commit"],
        "config_digest": identity["config_digest"],
        "workflow_ref": identity["workflow_ref"],
        "image_digest": identity["image_digest"],
        "sdk_digest": identity["sdk_digest"],
        "toolchain_image_digests": {
            contract["toolchain_id"]: (
                hmmer_digest
                if tool_name in {"hmmbuild", "hmmalign"}
                else _digest(f"{tool_name}-sif")
            )
            for tool_name, contract in live.AOX_TOOLCHAIN_RUNTIME_CONTRACTS.items()
        },
        "credential_slots": {
            "llm": True,
            "ncbi": True,
            "semantic_scholar": False,
            "tavily": False,
        },
        "ncbi_identity": _digest("ncbi-identity"),
        "prompt_accessions": {
            "formal_ncbi": list(aox_reference.NCBI_REFERENCE_ACCESSIONS),
            "probe_ncbi": list(live.KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
            "probe_uniprot": list(live.KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
        },
    }


def _operation() -> ControlledOperation:
    material = {
        "schema_version": "s12.adapter_envelope.v1",
        "sandbox_workspace_id": "sandbox_workspace_001",
        "source_snapshot_digest": _digest("source"),
        "sdk_module": "bio_tools",
        "function_name": "mafft",
        "params_digest": _digest("params"),
        "input_artifact_ids": ["art_input"],
        "input_artifact_digests": [_digest("input")],
        "placement": "hpc",
        "hpc_workspace_id": "hpcws_001",
        "stage_refs": [
            {
                "kind": "hpc_stage_ref",
                "stage_ref_id": "stage_001",
                "hpc_workspace_id": "hpcws_001",
                "artifact_id": "art_input",
                "artifact_digest": _digest("input"),
                "workspace_relative_path": "inputs/query.fasta",
            }
        ],
        "selected_backend": "hpc",
        "route_reason": "static_policy:v1",
        "route_policy_id": "bio_tools.mafft.hpc:v1",
        "runtime_packaging_id": "hpc_apptainer_sif.aox_hmm_2026_05_30",
        "toolchain_id": "mafft_7.525.hpc_apptainer_sif:v1",
        "provider_config_digest": None,
        "resource_class": "hpc_batch_small",
        "resource_estimate": {
            "placement": "hpc",
            "resource_class": "hpc_batch_small",
        },
        "expected_outputs": {
            "declared_outputs": [{"path": "outputs/alignment.fasta", "format": "fasta"}]
        },
        "planned_fetch_intent": {
            "declared_outputs": [{"path": "outputs/alignment.fasta", "format": "fasta"}]
        },
        "approval_requirement": {"required": True},
    }
    return ControlledOperation(
        operation_id="op_001",
        session_id="sess_001",
        sandbox_workspace_id="sandbox_workspace_001",
        sandbox_run_id="sandbox_run_001",
        logical_operation_key="bio_tools.mafft:key",
        operation_digest=controlled_operation_digest(material),
        params_digest=_digest("params"),
        backend_category="hpc",
        status=ControlledOperationStatus.COMPLETED,
        created_at="2026-07-17T00:00:00+00:00",
        updated_at="2026-07-17T00:00:01+00:00",
        approval_id="approval_001",
        approval_state="approved",
        route_reason="static_policy:v1",
        input_artifact_digests=(_digest("input"),),
        source_snapshot_artifact_id="art_source",
        source_snapshot_digest=_digest("source"),
        adapter_envelope_schema_version="s12.adapter_envelope.v1",
        sdk_module="bio_tools",
        function_name="mafft",
        route_policy_id="bio_tools.mafft.hpc:v1",
        placement="hpc",
        hpc_workspace_id="hpcws_001",
        selected_backend="hpc",
        resource_class="hpc_batch_small",
        runtime_packaging_id="hpc_apptainer_sif.aox_hmm_2026_05_30",
        toolchain_id="mafft_7.525.hpc_apptainer_sif:v1",
        input_artifact_ids=("art_input",),
        stage_refs=tuple(material["stage_refs"]),
        planned_fetch_intent=dict(material["planned_fetch_intent"]),
        approval_requirement={"required": True},
        adapter_result_envelope={"backend_run_id": "job_001"},
        expected_outputs_summary=dict(material["expected_outputs"]),
        resource_estimate=dict(material["resource_estimate"]),
        result_summary={
            "toolchain_runtime_identity": {
                "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
                "attestation_scope": "same_ssh_login_shell_pre_exec",
                "execution_mode": "ssh",
                "tool_id": "bio_tools.mafft",
                "adapter_id": "bio_tools.mafft",
                "command_template_id": "bio_tools_mafft_sif_v1",
                "runner_contract_digest": _digest("runner-contract"),
                "image_digest": _digest("mafft-sif"),
            }
        },
    )


def test_live_collector_preserves_exact_control_plane_operation_digest() -> None:
    operation = _operation()
    material = live.controlled_operation_identity_material(operation)
    record = live.operation_evidence_record(
        operation,
        scope="probe",
        inputs=[{"artifact_id": "art_input", "content_digest": _digest("input")}],
        outputs=[{"artifact_id": "art_output", "content_digest": _digest("output")}],
    )

    assert controlled_operation_digest(material) == operation.operation_digest
    assert record["operation_identity_schema"] == (
        "openzyme_controlled_operation_s12@1"
    )
    assert record["operation_identity_digest"] == operation.operation_digest
    assert record["backend_run_id"] == "job_001"


def test_public_api_receipt_normalizes_events_query_to_canonical_route() -> None:
    client = live._PublicHostClient(object())

    client._record(
        "GET",
        "/v3/sessions/sess_001/events?replay=1&after_cursor=7",
        None,
        b"data: {}\n",
        200,
    )

    assert (
        client.receipts[0].route
        == "/v3/sessions/sess_001/events?replay=1&after_cursor=7"
    )
    assert client.receipts[0].request_digest == live.canonical_digest(
        {"replay": True, "after_cursor": 7}
    )
    assert client.receipts[0].response_semantic_digest == live.canonical_digest([{}])


def test_public_api_receipts_reserve_at_start_and_seal_in_sequence_order() -> None:
    raw_client = _OutOfOrderJsonClient()
    client = live._PublicHostClient(raw_client)
    results: dict[str, tuple[dict[str, object], live.PublicApiReceipt]] = {}
    errors: dict[str, BaseException] = {}
    finished = {route: threading.Event() for route in raw_client.routes}

    def request(route: str) -> None:
        try:
            payload = client.get_json(route)
            results[route] = (payload, client.last_receipt)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors[route] = exc
        finally:
            finished[route].set()

    first_route, second_route = raw_client.routes
    first = threading.Thread(target=request, args=(first_route,))
    second = threading.Thread(target=request, args=(second_route,))
    first.start()
    try:
        assert raw_client.started[first_route].wait(timeout=1.0)
        second.start()
        assert raw_client.started[second_route].wait(timeout=1.0)

        raw_client.release[second_route].set()
        assert finished[second_route].wait(timeout=1.0)
        assert [receipt.sequence for receipt in client.receipts] == [2]
        with pytest.raises(live.LiveProductPathError) as inflight:
            client.sealed_receipts
        assert inflight.value.code == "public_api_receipt_chain_incomplete"
        with pytest.raises(live.LiveProductPathError) as main_thread:
            client.last_receipt
        assert main_thread.value.code == "public_api_response_receipt_missing"

        raw_client.release[first_route].set()
        assert finished[first_route].wait(timeout=1.0)
    finally:
        for release in raw_client.release.values():
            release.set()
        first.join(timeout=2.0)
        if second.ident is not None:
            second.join(timeout=2.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == {}
    assert [receipt.sequence for receipt in client.sealed_receipts] == [1, 2]
    assert results[first_route][0] == {"route": first_route}
    assert results[first_route][1].sequence == 1
    assert results[first_route][1].route == first_route
    assert results[second_route][0] == {"route": second_route}
    assert results[second_route][1].sequence == 2
    assert results[second_route][1].route == second_route
    assert results[first_route][1].response_semantic_digest == live.canonical_digest(
        results[first_route][0]
    )
    assert results[second_route][1].response_semantic_digest == live.canonical_digest(
        results[second_route][0]
    )


def test_public_api_transport_failure_preserves_completed_failure_receipts() -> None:
    class CompletedThenDisconnectedClient:
        base_url = "http://127.0.0.1:54321"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def get(self, route: str) -> _JsonResponse:
            self.calls.append(route)
            if route == "/v3/runtime/health":
                return _JsonResponse({"status": "ready"})
            assert route == "/v3/sessions/sess_transport/workspace"
            raise httpx.ConnectError(
                "deterministic connection failure",
                request=httpx.Request("GET", f"{self.base_url}{route}"),
            )

    raw_client = CompletedThenDisconnectedClient()
    client = live._PublicHostClient(raw_client)

    assert client.get_json("/v3/runtime/health") == {"status": "ready"}
    with pytest.raises(live.LiveProductPathError) as transport_error:
        client.get_json("/v3/sessions/sess_transport/workspace")

    assert transport_error.value.code == "host_public_api_transport_failed"
    assert transport_error.value.details == {
        "route": "/v3/sessions/sess_transport/workspace",
        "failure_type": "ConnectError",
    }
    completed = client.failure_receipts
    assert [receipt.sequence for receipt in completed] == [1]
    assert [receipt.route for receipt in completed] == ["/v3/runtime/health"]
    assert client.failure_receipts == completed
    assert transport_error.value.code == "host_public_api_transport_failed"

    with pytest.raises(live.LiveProductPathError) as sealing_error:
        client.sealed_receipts

    assert sealing_error.value.code == "public_api_receipt_chain_incomplete"
    assert sealing_error.value.details == {
        "inflight_count": 0,
        "failed_count": 1,
    }
    assert client.failure_receipts == completed
    assert raw_client.calls == [
        "/v3/runtime/health",
        "/v3/sessions/sess_transport/workspace",
    ]


def test_toolchain_collector_seals_exact_runner_attested_identity() -> None:
    operation = _operation()

    receipt = live._toolchain_receipt(
        tool_name="mafft",
        operation=operation,
        operation_record={"backend_run_id": "job_001"},
    )

    assert receipt == {
        "toolchain_record_id": "toolchain_record_op_001",
        "toolchain_id": "mafft_7.525.hpc_apptainer_sif:v1",
        "tool": "mafft",
        "operation_id": "op_001",
        "job_id": "job_001",
        "runtime_identity_schema": "mcp_hpc_toolchain_runtime_identity@1",
        "attestation_scope": "same_ssh_login_shell_pre_exec",
        "execution_mode": "ssh",
        "tool_id": "bio_tools.mafft",
        "adapter_id": "bio_tools.mafft",
        "command_template_id": "bio_tools_mafft_sif_v1",
        "runner_contract_digest": _digest("runner-contract"),
        "image_digest": _digest("mafft-sif"),
        "status": "completed",
    }


def test_toolchain_collector_rejects_compatibility_or_envelope_fallback() -> None:
    baseline = _operation()
    runtime_identity = dict(
        dict(baseline.result_summary or {})["toolchain_runtime_identity"]
    )
    operation = replace(
        baseline,
        result_summary={
            "compatibility": {"image_digest": runtime_identity["image_digest"]}
        },
        adapter_result_envelope={
            "backend_run_id": "job_001",
            "bounded_summary": {
                "compatibility": {"image_digest": runtime_identity["image_digest"]},
                "toolchain_runtime_identity": runtime_identity,
            },
        },
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live._toolchain_receipt(
            tool_name="mafft",
            operation=operation,
            operation_record={"backend_run_id": "job_001"},
        )

    assert error.value.code == "toolchain_image_identity_missing"


def test_live_collector_rejects_approval_identity_drift() -> None:
    operation = replace(_operation(), operation_digest=_digest("drift"))

    with pytest.raises(live.LiveProductPathError) as error:
        live.controlled_operation_identity_material(operation)

    assert error.value.code == "controlled_operation_digest_mismatch"


def test_probe_runtime_completion_requires_the_full_v2_operation_set() -> None:
    assert live._KNOWN_POSITIVE_PROBE_CONTROLLED_OPERATIONS == {
        ("bio", "ncbi_fetch_proteins"),
        ("bio", "uniprot_fetch"),
        ("bio_tools", "mafft"),
        ("bio_tools", "hmmbuild"),
        ("bio_tools", "cdhit"),
        ("bio_tools", "hmmalign"),
    }


def _ready_health(*, image_digest: str, sdk_digest: str) -> dict[str, object]:
    return {
        "schema_version": "v3.runtime_health.v1",
        "status": "ready",
        "deployment_profile": "local-dev",
        "storage_profile": "single_process_sqlite",
        "components": {
            "model": {"status": "ready", "details": {}},
            "execution": {"status": "ready", "details": {}},
            "bio_research": {"status": "ready", "details": {}},
            "sandbox": {
                "status": "ready",
                "details": {
                    "image_digest": image_digest,
                    "pipeline_sdk_digest": sdk_digest,
                    "runtime_identity_digest": _digest("runtime"),
                    "sandbox_protocol_version": "openzyme-sandbox.v1",
                },
            },
        },
    }


def test_live_runner_bootstraps_verified_sandbox_image_into_fresh_sqlite(
    tmp_path: Path,
) -> None:
    identity = _identity()
    provider = SQLiteRepositoryProvider(str(tmp_path / "blank-world.sqlite3"))
    health = _ready_health(
        image_digest=identity["image_digest"],
        sdk_digest=identity["sdk_digest"],
    )

    live.LiveAoxAttemptRunner._bootstrap_sandbox_runtime_identity(
        provider,
        health=health,
        identity=identity,
    )

    with provider.read() as scope:
        image = scope.repositories.sandbox_images.get_default()
    assert image is not None
    assert image.image_ref == (
        "localhost/openzyme-pipeline-sandbox@" + identity["image_digest"]
    )
    assert image.image_digest == identity["image_digest"]
    assert image.compatibility.value == "compatible"
    assert live._safe_health(health)["sandbox_runtime_identity"] == {
        "image_digest": identity["image_digest"],
        "pipeline_sdk_digest": identity["sdk_digest"],
        "runtime_identity_digest": _digest("runtime"),
        "sandbox_protocol_version": "openzyme-sandbox.v1",
    }


@pytest.mark.parametrize("mismatched_field", ("image_digest", "sdk_digest"))
def test_live_runner_rejects_campaign_sandbox_identity_drift_before_registration(
    tmp_path: Path,
    mismatched_field: str,
) -> None:
    identity = _identity()
    actual = dict(identity)
    actual[mismatched_field] = _digest(f"drift-{mismatched_field}")
    provider = SQLiteRepositoryProvider(str(tmp_path / "blank-world.sqlite3"))

    with pytest.raises(live.LiveProductPathError) as error:
        live.LiveAoxAttemptRunner._bootstrap_sandbox_runtime_identity(
            provider,
            health=_ready_health(
                image_digest=actual["image_digest"],
                sdk_digest=actual["sdk_digest"],
            ),
            identity=identity,
        )

    assert error.value.code == "campaign_sandbox_identity_mismatch"
    assert error.value.details == {"mismatched_fields": [mismatched_field]}
    with provider.read() as scope:
        assert scope.repositories.sandbox_images.get_default() is None


@pytest.mark.parametrize("missing_field", ("image_digest", "sdk_digest"))
def test_live_runner_rejects_missing_canonical_sandbox_runtime_identity(
    tmp_path: Path,
    missing_field: str,
) -> None:
    identity = _identity()
    actual = dict(identity)
    actual[missing_field] = "sha256:short"
    provider = SQLiteRepositoryProvider(str(tmp_path / "blank-world.sqlite3"))

    with pytest.raises(live.LiveProductPathError) as error:
        live.LiveAoxAttemptRunner._bootstrap_sandbox_runtime_identity(
            provider,
            health=_ready_health(
                image_digest=actual["image_digest"],
                sdk_digest=actual["sdk_digest"],
            ),
            identity=identity,
        )

    assert error.value.code == "sandbox_runtime_identity_missing"
    with provider.read() as scope:
        assert scope.repositories.sandbox_images.get_default() is None


def test_live_runner_rejects_preexisting_sandbox_image_registry_row(
    tmp_path: Path,
) -> None:
    identity = _identity()
    provider = SQLiteRepositoryProvider(str(tmp_path / "blank-world.sqlite3"))
    inherited_digest = _digest("inherited-image")
    with provider.write() as scope:
        scope.repositories.sandbox_images.save(
            live.sandbox_image_record(
                image_ref=live.DEFAULT_SANDBOX_IMAGE_REF,
                image_digest=inherited_digest,
            )
        )

    with pytest.raises(live.LiveProductPathError) as error:
        live.LiveAoxAttemptRunner._bootstrap_sandbox_runtime_identity(
            provider,
            health=_ready_health(
                image_digest=identity["image_digest"],
                sdk_digest=identity["sdk_digest"],
            ),
            identity=identity,
        )

    assert error.value.code == "sandbox_image_registry_not_blank"
    with provider.read() as scope:
        image = scope.repositories.sandbox_images.get_default()
    assert image is not None
    assert image.image_digest == inherited_digest


def test_live_runner_registers_sandbox_identity_before_first_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    ledger_path = tmp_path / "persistent-micu-ledger.sqlite3"
    settings = OpenZymeSettings.from_env()
    settings = replace(
        settings,
        test=replace(
            settings.test,
            live_llm=replace(
                settings.test.live_llm,
                token_ledger_path=str(ledger_path),
            ),
        ),
    )
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    context = AttemptRunContext(
        roots=roots,
        identity=identity,
        ledger_before=safe_micu_ledger_snapshot(ledger_path),
        attempt_number=1,
    )
    health = _ready_health(
        image_digest=identity["image_digest"],
        sdk_digest=identity["sdk_digest"],
    )

    class Response:
        status_code = 200
        content = b'{"status":"ready"}'

        @staticmethod
        def json() -> dict[str, object]:
            return health

    class Client:
        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> None:
            del args
            assert not (
                roots.artifact_root / "formal/live-product-path-blocker.json"
            ).exists()

        @staticmethod
        def get(route: str) -> Response:
            assert route == "/v3/runtime/health"
            return Response()

    observed = {"registered_before_session": False}

    def stop_at_first_session(
        self: live.LiveAoxAttemptRunner,
        api: live._PublicHostClient,
        provider: SQLiteRepositoryProvider,
        **kwargs: object,
    ) -> None:
        del self, kwargs
        with provider.read() as scope:
            image = scope.repositories.sandbox_images.get_default()
        observed["registered_before_session"] = (
            image is not None and image.image_digest == identity["image_digest"]
        )
        assert [receipt.route for receipt in api.receipts] == ["/v3/runtime/health"]
        raise live.LiveProductPathError("test_stop", "stop before session creation")

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_settings_blocker",
        lambda self, context: None,
    )
    monkeypatch.setattr(live, "build_configured_foundation", lambda **kwargs: object())
    monkeypatch.setattr(live, "create_app", lambda dependencies: object())
    monkeypatch.setattr(live, "_LoopbackHost", lambda **kwargs: Client())
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner, "_run_session", stop_at_first_session
    )
    runner = live.LiveAoxAttemptRunner(settings=settings, ledger_path=ledger_path)

    evidence = runner(context)

    assert observed["registered_before_session"] is True
    assert evidence["scientific_outcome"]["blocker_code"] == "test_stop"


def test_known_positive_probe_prompt_exposes_fixed_runner_output_contracts(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    prompt = runner._probe_prompt(
        AttemptRunContext(
            roots=roots,
            identity=_identity(),
            ledger_before=safe_micu_ledger_snapshot(ledger_path),
            attempt_number=1,
        )
    )

    assert "campaign already enforces provider cache bypass" in prompt
    assert "do not invent unsupported cache flags" in prompt
    assert "result_summary.transcript_manifest.files" in prompt
    assert "/provider_parsed/proteins.fasta" in prompt
    assert "/provider_parsed/sequences.fasta" in prompt
    assert "adapter_result_envelope ID lists" in prompt
    assert "bio_tools/mafft/alignment.fasta" in prompt
    assert "bio_tools/hmmbuild/model.hmm" in prompt
    assert "bio_tools/cdhit/clustered.fasta" in prompt
    assert "bio_tools/cdhit/clusters.csv" in prompt
    assert "bio_tools/hmmalign/aligned.fasta" in prompt
    assert "all four run handles, including the terminal HMMalign" in prompt
    assert "unique fetch_refs entry whose declared_output_path" in prompt
    assert "never by registered_artifact_ids or artifacts list order" in prompt


def test_formal_prompt_exposes_host_owned_cache_bypass_contract(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )

    prompt = runner._formal_prompt(
        AttemptRunContext(
            roots=roots,
            identity=_identity(),
            ledger_before=safe_micu_ledger_snapshot(ledger_path),
            attempt_number=1,
        )
    )

    assert "campaign already enforces evidence-bearing provider cache bypass" in prompt
    assert "do not pass or invent unsupported cache flags" in prompt
    assert f"workflow_refs=[{_identity()['workflow_ref']!r}] only to the executor" in prompt
    assert "researcher and reporter must omit workflow_refs" in prompt
    assert "openzyme_pipeline.aox_reference.select_hmm_reference_set" in prompt
    assert "openzyme_pipeline.aox_reference.select_scoring_reference" in prompt
    assert "openzyme_pipeline.aox_reference.assemble_scoring_input" in prompt
    assert "openzyme_pipeline.aox_hmmer.parse_and_filter_csv" in prompt
    assert "openzyme_pipeline.aox_sequence_join.join_score_filtered_accessions" in prompt
    assert "openzyme_pipeline.aox_motif.score_aligned_fasta" in prompt
    assert "openzyme_pipeline.aox_similarity.build_similarity_graph" in prompt
    assert "/provider_parsed/proteins.fasta" in prompt
    assert "/provider_parsed/parsed_hits.csv" in prompt
    assert "/provider_parsed/sequences.fasta" in prompt
    assert "/provider_parsed/metadata.json" in prompt
    assert "bio_tools/mafft/alignment.fasta" in prompt
    assert "bio_tools/hmmbuild/model.hmm" in prompt
    assert "bio_tools/cdhit/clustered.fasta" in prompt
    assert "bio_tools/cdhit/clusters.csv" in prompt
    assert "bio_tools/hmmalign/aligned.fasta" in prompt
    assert "unique fetch_refs entry" in prompt
    assert "exact fetched hmmbuild artifact id and content digest" in prompt
    assert "validation_profile='fasta_zero_records@1'" in prompt
    assert (
        "join_score_filtered_accessions(score_filtered_csv, uniprot_fasta, "
        "uniprot_metadata_json, ...)" in prompt
    )
    assert (
        "build_similarity_graph(candidate_fasta, cdhit_membership_csv, ...)"
        in prompt
    )
    assert "supply every bound expected_*_digest" in prompt
    assert "never reimplement or approximate" in prompt


def test_formal_delegation_workflow_binding_is_exact_and_executor_scoped(
    tmp_path: Path,
) -> None:
    workflow = next(
        manifest
        for manifest in live.default_workflow_registry().list_manifests()
        if manifest.workflow_id == "aox-hmm-live"
    )
    identity = {**_identity(), "workflow_ref": workflow.selection_ref}
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites={
            **_allowed_prerequisites(),
            "workflow_ref": workflow.selection_ref,
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=identity,
        ledger_before=safe_micu_ledger_snapshot(tmp_path / "ledger.sqlite3"),
        attempt_number=1,
    )
    task_receipts = [
        {
            "task_id": f"task_{role}",
            "role": role,
            "status": "completed",
            "business_exit": "agent_explicit",
            "assigned_ref": f"agent_{role}",
        }
        for role in ("researcher", "executor", "reporter")
    ]
    documents = tuple(
        SimpleNamespace(
            document_id=f"doc_{role}",
            document_kind="delegation_request",
            payload={
                "task_id": f"task_{role}",
                "instructions": f"Complete the canonical {role} task.",
                "role": role,
                "agent_id": f"agent_{role}",
                "nickname": role,
                "display_name": role.capitalize(),
                "handle": f"@{role}",
                "workflow_refs": [workflow.selection_ref]
                if role == "executor"
                else [],
                "workflow_manifests": [workflow.to_dict()]
                if role == "executor"
                else [],
            },
        )
        for role in ("researcher", "executor", "reporter")
    )

    bound = live._bind_delegation_workflow_receipts(
        context,
        task_receipts=task_receipts,
        documents=documents,
    )

    by_role = {str(item["role"]): item for item in bound}
    assert by_role["executor"]["workflow_refs"] == [workflow.selection_ref]
    assert by_role["executor"]["workflow_manifests"] == [workflow.to_dict()]
    assert by_role["researcher"]["workflow_refs"] == []
    assert by_role["reporter"]["workflow_refs"] == []
    assert all(item["delegation_request_ref"] for item in bound)
    assert all(item["delegation_request_digest"] for item in bound)
    assert all(
        item["delegation_request"]["document_id"]
        == item["delegation_request_ref"]
        and item["delegation_request"]["agent_id"] == item["assigned_ref"]
        and live.canonical_digest(item["delegation_request"])
        == item["delegation_request_digest"]
        for item in bound
    )

    drifted = list(documents)
    drifted[0] = SimpleNamespace(
        document_id="doc_researcher",
        document_kind="delegation_request",
        payload={
            **dict(documents[0].payload),
            "workflow_refs": [workflow.selection_ref],
            "workflow_manifests": [workflow.to_dict()],
        },
    )
    with pytest.raises(live.LiveProductPathError) as error:
        live._bind_delegation_workflow_receipts(
            context,
            task_receipts=task_receipts,
            documents=tuple(drifted),
        )
    assert error.value.code == "formal_delegation_workflow_binding_invalid"


def test_catalog_source_snapshot_directory_is_sealed_as_self_verifying_envelope(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    source_root = roots.blob_root / "sealed" / "source" / "snapshot"
    files = {
        "openzyme_pipeline/__init__.py": b"from .worker import run\n",
        "openzyme_pipeline/worker.py": b"def run():\n    return 1\n",
    }
    for relative_path, content in files.items():
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    tree_digest = live.canonical_digest(
        [
            {
                "relative_path": relative_path,
                "content_digest": "sha256:"
                + hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for relative_path, content in sorted(files.items())
        ]
    )
    artifact = SimpleNamespace(
        artifact_id="art_source_snapshot",
        storage_uri=str(source_root),
        kind=ArtifactKind.CODE,
        metadata={
            "semantic_type": "pipeline_source_snapshot",
            "format": "source_tree",
            "source_tree_digest": tree_digest,
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(ledger_path),
        attempt_number=1,
    )

    sealed = live._artifact_bytes(context, artifact)
    envelope = cutover_evidence.verify_sealed_source_tree_envelope(
        sealed,
        expected_source_tree_digest=tree_digest,
    )

    assert envelope["schema_id"] == "openzyme_sealed_source_tree@1"
    assert [item["relative_path"] for item in envelope["files"]] == sorted(files)


def test_catalog_source_snapshot_directory_rejects_metadata_digest_drift(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    source_root = roots.blob_root / "sealed" / "source" / "snapshot"
    source_root.mkdir(parents=True)
    (source_root / "main.py").write_text("value = 1\n", encoding="utf-8")
    artifact = SimpleNamespace(
        artifact_id="art_source_snapshot",
        storage_uri=str(source_root),
        kind=ArtifactKind.CODE,
        metadata={
            "semantic_type": "pipeline_source_snapshot",
            "format": "source_tree",
            "source_tree_digest": _digest("wrong-tree"),
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(ledger_path),
        attempt_number=1,
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live._artifact_bytes(context, artifact)

    assert error.value.code == "sealed_source_tree_digest_mismatch"


def test_catalog_source_snapshot_directory_requires_code_kind(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    source_root = roots.blob_root / "sealed" / "source" / "snapshot"
    source_root.mkdir(parents=True)
    content = b"value = 1\n"
    (source_root / "main.py").write_bytes(content)
    artifact = SimpleNamespace(
        artifact_id="art_source_snapshot",
        storage_uri=str(source_root),
        kind=ArtifactKind.RESULT,
        metadata={
            "semantic_type": "pipeline_source_snapshot",
            "format": "source_tree",
            "source_tree_digest": live.canonical_digest(
                [
                    {
                        "relative_path": "main.py",
                        "content_digest": "sha256:"
                        + hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                    }
                ]
            ),
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(tmp_path / "ledger.sqlite3"),
        attempt_number=1,
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live._artifact_bytes(context, artifact)

    assert error.value.code == "catalog_artifact_blob_invalid"


def test_catalog_copy_seals_typed_zero_fasta_registration_receipt(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    source = roots.blob_root / "sealed" / "empty-target.fasta"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"")
    reason = "no_hmmer_hits"
    derivation = "aox_upstream_empty_materialization@1"
    validation = {
        "status": "passed",
        "format": "fasta",
        "required_columns": [],
        "validation_profile": "fasta_zero_records@1",
        "empty_result_reason": reason,
        "derivation_contract_id": derivation,
    }
    artifact = SessionArtifactRecord(
        artifact_id="art_empty_target",
        session_id="session_test",
        task_id="task_test",
        lane_id="lane_test",
        invocation_id=None,
        run_id="run_test",
        kind=ArtifactKind.SEQUENCE,
        storage_uri=str(source),
        relative_path="aox_hmm/target.fasta",
        created_at="2026-07-18T00:00:00+00:00",
        metadata={
            "content_digest": "sha256:" + hashlib.sha256(b"").hexdigest(),
            "format": "fasta",
            "validation_profile": "fasta_zero_records@1",
            "empty_result_reason": reason,
            "derivation_contract_id": derivation,
            "validation": validation,
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(tmp_path / "ledger.sqlite3"),
        attempt_number=1,
    )

    copy = live._copy_catalog_artifact(
        context,
        artifact,
        scope="formal",
        origin="operation",
        provenance={"operation_id": "op_empty"},
        cache={},
    )

    assert copy.content == b""
    assert copy.record["registration_validation"] == {
        **copy.record["registration_validation"],
        "schema_id": "openzyme_typed_empty_artifact_validation@1",
        "kind": "sequence",
        "format": "fasta",
        "validation_profile": "fasta_zero_records@1",
        "empty_result_reason": reason,
        "derivation_contract_id": derivation,
        "catalog_validation_digest": live.canonical_digest(validation),
    }


def test_public_driver_route_surface_rejects_debug_shortcut() -> None:
    class Response:
        status_code = 200
        content = b'{"status":"ready"}'

        @staticmethod
        def json() -> dict[str, str]:
            return {"status": "ready"}

    class Client:
        @staticmethod
        def get(route: str) -> Response:
            assert route == "/v3/runtime/health"
            return Response()

    client = live._PublicHostClient(Client())
    assert client.get_json("/v3/runtime/health") == {"status": "ready"}
    with pytest.raises(live.LiveProductPathError) as error:
        client.get_json("/debug/v3-runtime")

    assert error.value.code == "noncanonical_api_route_forbidden"
    assert [receipt.route for receipt in client.receipts] == ["/v3/runtime/health"]


def test_live_report_collector_binds_ready_report_draft_document_and_events(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(tmp_path / "ledger.sqlite3"),
        attempt_number=1,
    )
    report = SessionReportRecord(
        report_id="report_aox",
        session_id="sess_aox",
        task_id="task_report",
        lane_id="lane_report",
        invocation_id=None,
        run_id=None,
        artifact_id=None,
        status=SessionReportStatus.READY,
        title="AOX report",
        summary="summary",
        stage_summary="stage",
        created_at="2026-07-17T00:00:02+00:00",
        updated_at="2026-07-17T00:00:03+00:00",
    )
    draft = SessionReportDraftRecord(
        draft_id="draft_aox",
        session_id="sess_aox",
        task_id="task_report",
        owner_agent_id="agent_reporter",
        status=SessionReportDraftStatus.PUBLISHED,
        title="AOX report",
        summary="summary",
        content_ref="doc_report_aox",
        published_report_id="report_aox",
        created_at="2026-07-17T00:00:01+00:00",
        updated_at="2026-07-17T00:00:03+00:00",
    )
    markdown = (
        "# AOX report\n\nPMID 12345678 source_pubmed_aox "
        "uses sealed artifact art_science.\n"
    )
    document = EngineDocumentRecord(
        document_id="doc_report_aox",
        session_id="sess_aox",
        invocation_id=None,
        document_kind="report_draft_content",
        payload={"markdown": markdown},
        created_at="2026-07-17T00:00:01+00:00",
        updated_at="2026-07-17T00:00:01+00:00",
    )
    invoked_payload = {
        "call_id": "call_publish",
        "tool_name": "report.publish",
        "task_id": "task_report",
        "lane_id": "lane_report",
        "role": "reporter",
    }
    completed_payload = {
        **invoked_payload,
        "ok": True,
        "status": "ok",
    }
    events = tuple(
        DurableEventRecord(
            event_id=f"event_{cursor}",
            session_id="sess_aox",
            event_type=event_type,
            created_at=f"2026-07-17T00:00:0{cursor - 38}+00:00",
            payload=payload,
            cursor=cursor,
        )
        for cursor, event_type, payload in (
            (40, "tool.invoked", invoked_payload),
            (41, "report_draft.updated", draft.to_dict()),
            (42, "report.generated", report.to_dict()),
            (43, "tool.completed", completed_payload),
        )
    )
    science = live.CatalogArtifactCopy(
        record={
            "artifact_id": "art_science",
            "relative_path": "formal/science.csv",
            "provenance": {"catalog_relative_path": "aox_hmm/science.csv"},
        },
        content=b"result\n",
        content_digest=_digest("science"),
    )

    receipt, artifact, publish_events = live._published_report_receipt(
        context,
        reports=(report,),
        drafts=(draft,),
        documents=(document,),
        durable_events=events,
        pubmed_provider={
            "source_refs": [
                {
                    "source_ref_id": "source_pubmed_aox",
                    "pmid": "12345678",
                }
            ]
        },
        scientific_artifacts=[science],
    )

    assert _report_publish_receipt_is_valid(receipt)
    assert receipt["content_document_digest"] != receipt["content_digest"]
    assert receipt["publish_events"] == publish_events
    assert artifact["provenance"]["content_ref"] == "doc_report_aox"
    assert (
        roots.artifact_root / str(artifact["relative_path"])
    ).read_bytes() == markdown.encode("utf-8")


def test_live_runner_seals_exact_no_go_when_live_opt_in_is_absent(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "persistent-micu-ledger.sqlite3"
    settings = OpenZymeSettings.from_env()
    settings = replace(
        settings,
        test=replace(
            settings.test,
            enable_live_e2e=False,
            live_llm=replace(
                settings.test.live_llm,
                token_ledger_path=str(ledger_path),
            ),
        ),
    )
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-no-opt-in",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    before = safe_micu_ledger_snapshot(ledger_path)
    runner = live.LiveAoxAttemptRunner(settings=settings, ledger_path=ledger_path)
    evidence = runner(
        AttemptRunContext(
            roots=roots,
            identity=_identity(),
            ledger_before=before,
            attempt_number=1,
        )
    )

    assert evidence["scientific_outcome"] == {
        "status": "failed",
        "failure_code": "live_e2e_not_enabled",
        "blocker_code": "live_e2e_not_enabled",
        "cutover_eligible": False,
    }
    payload = build_attempt_bundle(
        attempt_id=roots.attempt_id,
        attempt_kind="positive",
        identity=_identity(),
        clean_world=roots.proof,
        ledger_before=before,
        ledger_after=safe_micu_ledger_snapshot(ledger_path),
        artifact_root=roots.artifact_root,
        evidence=evidence,
        sealed_at="2026-07-17T00:00:00+00:00",
    )
    bundle_path = roots.evidence_root / "attempt-bundle.json"
    seal_attempt_bundle(payload, bundle_path)

    verification = verify_attempt_bundle(bundle_path, artifact_root=roots.artifact_root)
    assert verification.passed, verification.to_dict()


def test_cli_exposes_real_live_campaign_command(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-live",
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--identity",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites",
            str(tmp_path / "prerequisites.json"),
        ]
    )

    assert args.command == "run-live"
    assert args.approval_mode == "auto"
    assert args.max_drains == 120
    assert args.browser_completion_hold_seconds == 60.0


def _runner_settings(ledger_path: Path) -> OpenZymeSettings:
    settings = OpenZymeSettings.from_env()
    return replace(
        settings,
        test=replace(
            settings.test,
            live_llm=replace(
                settings.test.live_llm,
                token_ledger_path=str(ledger_path),
            ),
        ),
    )


def _minimal_fault_injection_receipt() -> live.FaultInjectionReceipt:
    return live.FaultInjectionReceipt(
        source_artifact_id="art_source",
        source_artifact_digest=_digest("source-artifact"),
        target_artifact_id="art_target",
        target_relative_path="aox_hmm/AOX_ref21.fasta",
        source_operation_id="op_source",
        terminal_failure_operation_id="op_target",
        derivation_id="aox_hmm_reference_set_selection@1",
        derivation_contract_digest=_digest("derivation-contract"),
        derivation_implementation_digest=_digest("derivation-implementation"),
        consumer_tool_id="bio_tools.mafft",
        byte_offset=4,
        before_digest=_digest("before-fault"),
        after_digest=_digest("after-fault"),
        failure_code="artifact_blob_digest_mismatch",
    )


def test_live_runner_preserves_transport_blocker_when_receipt_chain_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-transport-failure",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(ledger_path),
        attempt_number=1,
    )

    class TransportFailingClient:
        base_url = "http://127.0.0.1:54321"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def __enter__(self) -> TransportFailingClient:
            return self

        def __exit__(self, *args: object) -> None:
            del args
            assert not (
                roots.artifact_root / "formal/live-product-path-blocker.json"
            ).exists()

        def get(self, route: str) -> _JsonResponse:
            self.calls.append(route)
            assert route == "/v3/runtime/health"
            raise httpx.ConnectError(
                "deterministic loopback transport failure",
                request=httpx.Request("GET", f"{self.base_url}{route}"),
            )

    raw_client = TransportFailingClient()
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_settings_blocker",
        lambda self, context: None,
    )
    monkeypatch.setattr(live, "build_configured_foundation", lambda **kwargs: object())
    monkeypatch.setattr(live, "create_app", lambda dependencies: object())
    monkeypatch.setattr(live, "_LoopbackHost", lambda **kwargs: raw_client)
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
    )

    evidence = runner(context)

    assert evidence["scientific_outcome"] == {
        "status": "failed",
        "failure_code": "host_public_api_transport_failed",
        "blocker_code": "host_public_api_transport_failed",
        "cutover_eligible": False,
    }
    assert evidence["report"]["cutover_eligible"] is False
    assert evidence["product_path"]["public_api_receipt_digest"] == (
        live.canonical_digest([])
    )
    blocker_payload = json.loads(
        (
            roots.artifact_root / "formal/live-product-path-blocker.json"
        ).read_text(encoding="utf-8")
    )
    assert blocker_payload["blocker"]["code"] == (
        "host_public_api_transport_failed"
    )
    assert blocker_payload["public_api_receipts"] == []
    assert raw_client.calls == ["/v3/runtime/health"]


def test_runtime_drain_coordinates_three_serial_approvals_while_blocked(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    approval_ids = ("approval_serial_1", "approval_serial_2", "approval_serial_3")
    raw_client = _SerialApprovalJsonClient(approval_ids)
    api = live._PublicHostClient(raw_client)

    try:
        coordination = runner._coordinate_runtime_drain(
            api,
            object(),  # type: ignore[arg-type]
            session_id="sess_serial",
            drain_number=1,
            started=time.monotonic(),
            pre_event_cursor=0,
            prior_approval_ids=frozenset(),
            browser_gate_enabled=False,
            browser_approval_receipt=None,
            fault_enabled=False,
            fault_blob_root=None,
            fault_receipt=None,
        )
    finally:
        raw_client.release_all()

    assert raw_client.drain_started.is_set()
    assert coordination.approval_ids == approval_ids
    assert coordination.workspace == {"pending_approvals": []}
    assert coordination.browser_approval_receipt is None
    assert coordination.fault_receipt is None
    assert raw_client.resolve_calls == [
        (approval_id, "approved", True) for approval_id in approval_ids
    ]
    assert coordination.workspace_response_binding["route"] == (
        "/v3/sessions/sess_serial/workspace"
    )
    assert coordination.workspace_response_binding[
        "response_semantic_digest"
    ] == live.canonical_digest(coordination.workspace)
    sealed = api.sealed_receipts
    assert [receipt.sequence for receipt in sealed] == list(
        range(1, len(sealed) + 1)
    )
    drain_receipts = [
        receipt
        for receipt in sealed
        if receipt.route == "/v3/sessions/sess_serial/runtime/drain"
    ]
    assert len(drain_receipts) == 1
    assert drain_receipts[0].sequence == 1
    assert all(
        not thread.is_alive() or thread.name != "aox-cutover-drain-1"
        for thread in threading.enumerate()
    )


def test_runtime_drain_resolves_approval_exposed_by_waiting_response(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    approval_id = "approval_after_bounded_drain"
    raw_client = _DrainReturnsPendingApprovalJsonClient(approval_id)
    api = live._PublicHostClient(raw_client)

    coordination = runner._coordinate_runtime_drain(
        api,
        object(),  # type: ignore[arg-type]
        session_id="sess_post_response",
        drain_number=2,
        started=time.monotonic(),
        pre_event_cursor=0,
        prior_approval_ids=frozenset(),
        browser_gate_enabled=False,
        browser_approval_receipt=None,
        fault_enabled=False,
        fault_blob_root=None,
        fault_receipt=None,
    )

    assert raw_client.drain_returned.is_set()
    assert raw_client.resolve_calls == [(approval_id, "approved", True)]
    assert coordination.approval_ids == (approval_id,)
    assert coordination.workspace == {"pending_approvals": []}
    assert all(
        not thread.is_alive() or thread.name != "aox-cutover-drain-2"
        for thread in threading.enumerate()
    )


def test_later_drain_auto_approves_after_chrome_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    approval_id = "approval_after_chrome_drain"
    raw_client = _DrainReturnsPendingApprovalJsonClient(approval_id)
    api = live._PublicHostClient(raw_client)
    chrome_receipt = {
        "schema_id": live.BROWSER_APPROVAL_RECEIPT_SCHEMA_ID,
        "approval_id": "approval_chrome_first",
    }

    def unexpected_browser_handoff(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("a later drain must not request a second Chrome approval")

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_wait_for_browser_approval",
        unexpected_browser_handoff,
    )

    coordination = runner._coordinate_runtime_drain(
        api,
        object(),  # type: ignore[arg-type]
        session_id="sess_post_response",
        drain_number=3,
        started=time.monotonic(),
        pre_event_cursor=0,
        prior_approval_ids=frozenset({"approval_chrome_first"}),
        browser_gate_enabled=True,
        browser_approval_receipt=chrome_receipt,
        fault_enabled=False,
        fault_blob_root=None,
        fault_receipt=None,
    )

    assert raw_client.resolve_calls == [(approval_id, "approved", True)]
    assert coordination.approval_ids == (approval_id,)
    assert coordination.browser_approval_receipt is chrome_receipt
    assert coordination.workspace == {"pending_approvals": []}


def test_runtime_drain_wraps_background_exception_as_stable_failure(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    api = live._PublicHostClient(_FailingDrainJsonClient())

    with pytest.raises(live.LiveProductPathError) as error:
        runner._coordinate_runtime_drain(
            api,
            object(),  # type: ignore[arg-type]
            session_id="sess_failed",
            drain_number=7,
            started=time.monotonic(),
            pre_event_cursor=0,
            prior_approval_ids=frozenset(),
            browser_gate_enabled=False,
            browser_approval_receipt=None,
            fault_enabled=False,
            fault_blob_root=None,
            fault_receipt=None,
        )

    assert error.value.code == "runtime_drain_command_failed"
    assert error.value.details == {"failure_type": "RuntimeError"}
    assert "private background failure detail" not in str(error.value)
    assert isinstance(error.value.__cause__, RuntimeError)
    assert all(
        not thread.is_alive() or thread.name != "aox-cutover-drain-7"
        for thread in threading.enumerate()
    )


def test_runtime_drain_failure_wins_over_concurrent_workspace_failure(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    drain_number = 10
    drain_thread_name = f"aox-cutover-drain-{drain_number}"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    raw_client = _ConcurrentDrainAndWorkspaceFailureJsonClient(
        drain_thread_name=drain_thread_name
    )
    api = live._PublicHostClient(raw_client)

    with pytest.raises(live.LiveProductPathError) as error:
        runner._coordinate_runtime_drain(
            api,
            object(),  # type: ignore[arg-type]
            session_id="sess_concurrent_failure",
            drain_number=drain_number,
            started=time.monotonic(),
            pre_event_cursor=0,
            prior_approval_ids=frozenset(),
            browser_gate_enabled=False,
            browser_approval_receipt=None,
            fault_enabled=False,
            fault_blob_root=None,
            fault_receipt=None,
        )

    assert raw_client.workspace_get_started.is_set()
    assert raw_client.drain_failure_started.is_set()
    assert error.value.code == "runtime_drain_command_failed"
    assert error.value.details == {"failure_type": "RuntimeError"}
    assert isinstance(error.value.__cause__, RuntimeError)
    assert str(error.value.__cause__) == (
        "private concurrent drain failure detail"
    )
    assert "workspace failure" not in str(error.value)
    assert all(
        not thread.is_alive() or thread.name != drain_thread_name
        for thread in threading.enumerate()
    )


def test_fault_injection_invariant_failure_rejects_pending_without_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    approval_id = "approval_fault_invariant"
    raw_client = _SerialApprovalJsonClient((approval_id,))
    api = live._PublicHostClient(raw_client)

    def fail_target_invariant(
        self: live.LiveAoxAttemptRunner,
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        approval_id: str,
        blob_root: Path,
    ) -> live.FaultInjectionReceipt | None:
        del self, provider, session_id, blob_root
        raw_client.call_order.append(f"inject:{approval_id}")
        raise live.LiveProductPathError(
            "fault_target_digest_binding_invalid",
            "fault target invariant failed before approval",
        )

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_inject_before_hpc_approval",
        fail_target_invariant,
    )

    try:
        with pytest.raises(live.LiveProductPathError) as error:
            runner._coordinate_runtime_drain(
                api,
                object(),  # type: ignore[arg-type]
                session_id="sess_serial",
                drain_number=8,
                started=time.monotonic(),
                pre_event_cursor=0,
                prior_approval_ids=frozenset(),
                browser_gate_enabled=False,
                browser_approval_receipt=None,
                fault_enabled=True,
                fault_blob_root=tmp_path / "blobs",
                fault_receipt=None,
            )
    finally:
        raw_client.release_all()

    assert error.value.code == "fault_target_digest_binding_invalid"
    assert raw_client.resolve_calls == [(approval_id, "rejected", True)]
    assert not any(
        decision == "approved"
        for _, decision, _ in raw_client.resolve_calls
    )
    assert raw_client.call_order == [
        f"inject:{approval_id}",
        f"resolve:{approval_id}:rejected",
    ]
    assert all(
        not thread.is_alive() or thread.name != "aox-cutover-drain-8"
        for thread in threading.enumerate()
    )


def test_fault_path_rejects_approval_after_target_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    before_target = "approval_before_fault_target"
    fault_target = "approval_fault_target"
    after_target = "approval_after_fault_target"
    approval_ids = (before_target, fault_target, after_target)
    raw_client = _SerialApprovalJsonClient(approval_ids)
    api = live._PublicHostClient(raw_client)
    receipt = _minimal_fault_injection_receipt()

    def inject_target_only(
        self: live.LiveAoxAttemptRunner,
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        approval_id: str,
        blob_root: Path,
    ) -> live.FaultInjectionReceipt | None:
        del self, provider, session_id, blob_root
        raw_client.call_order.append(f"inject:{approval_id}")
        if approval_id == before_target:
            return None
        if approval_id == fault_target:
            return receipt
        raise AssertionError("additional approval must fail before reinjection")

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_inject_before_hpc_approval",
        inject_target_only,
    )

    try:
        with pytest.raises(live.LiveProductPathError) as error:
            runner._coordinate_runtime_drain(
                api,
                object(),  # type: ignore[arg-type]
                session_id="sess_serial",
                drain_number=9,
                started=time.monotonic(),
                pre_event_cursor=0,
                prior_approval_ids=frozenset(),
                browser_gate_enabled=False,
                browser_approval_receipt=None,
                fault_enabled=True,
                fault_blob_root=tmp_path / "blobs",
                fault_receipt=None,
            )
    finally:
        raw_client.release_all()

    assert error.value.code == "fault_path_additional_approval_forbidden"
    assert error.value.details == {"approval_id": after_target}
    assert raw_client.resolve_calls == [
        (before_target, "approved", True),
        (fault_target, "approved", True),
        (after_target, "rejected", True),
    ]
    assert raw_client.call_order == [
        f"inject:{before_target}",
        f"resolve:{before_target}:approved",
        f"inject:{fault_target}",
        f"resolve:{fault_target}:approved",
        f"resolve:{after_target}:rejected",
    ]
    assert all(
        not thread.is_alive() or thread.name != "aox-cutover-drain-9"
        for thread in threading.enumerate()
    )


def test_same_process_loopback_host_serves_exact_app_and_stops() -> None:
    app = FastAPI()

    @app.get("/identity")
    def identity() -> dict[str, int]:
        return {"process_id": os.getpid()}

    host = live._LoopbackHost(app=app, request_timeout_seconds=5.0)
    with host as client:
        response = client.get("/identity")
        assert response.status_code == 200
        assert response.json() == {"process_id": os.getpid()}
        assert host.base_url.startswith("http://127.0.0.1:")

    assert host._thread is not None
    assert host._thread.is_alive() is False


def test_loopback_host_retires_if_ready_record_emission_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    host = live._LoopbackHost(app=app, request_timeout_seconds=5.0)

    def fail_ready_record(payload: object) -> None:
        del payload
        raise RuntimeError("operator stream unavailable")

    monkeypatch.setattr(live, "_emit_operator_record", fail_ready_record)

    with pytest.raises(RuntimeError, match="operator stream unavailable"):
        host.__enter__()

    assert host._thread is not None
    assert host._thread.is_alive() is False


def test_loopback_host_retires_server_thread_after_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingServer:
        started = False
        should_exit = False
        force_exit = False

        def __init__(self, config: object) -> None:
            del config

        @staticmethod
        def run(*, sockets: object) -> None:
            del sockets
            raise RuntimeError("loopback startup failed")

    monkeypatch.setattr(live.uvicorn, "Server", FailingServer)
    host = live._LoopbackHost(app=FastAPI(), request_timeout_seconds=5.0)

    with pytest.raises(live.LiveProductPathError) as error:
        host.__enter__()

    assert error.value.code == "browser_approval_host_start_failed"
    assert error.value.details == {"failure_type": "RuntimeError"}
    assert host._thread is not None
    assert host._thread.is_alive() is False


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_loopback_host_retires_server_mutation_after_client_timeout(
    method: str,
) -> None:
    app = FastAPI()
    handler_started = threading.Event()
    handler_finished = threading.Event()

    def blocking_mutation(session_id: str) -> dict[str, str]:
        handler_started.set()
        time.sleep(0.15)
        handler_finished.set()
        return {"session_id": session_id}

    app.add_api_route(
        "/v3/sessions/{session_id}/mutation",
        blocking_mutation,
        methods=[method],
    )
    host = live._LoopbackHost(
        app=app,
        request_timeout_seconds=0.02,
        shutdown_timeout_seconds=1.0,
    )
    with host as client:
        with pytest.raises(httpx.ReadTimeout):
            client.request(method, "/v3/sessions/sess_slow/mutation")
        assert handler_started.wait(timeout=1.0)
        assert handler_finished.is_set() is False

    assert handler_finished.is_set() is True
    assert host._thread is not None
    assert host._thread.is_alive() is False


def test_loopback_host_never_returns_while_server_thread_remains_alive() -> None:
    host = live._LoopbackHost(
        app=FastAPI(),
        request_timeout_seconds=1.0,
        shutdown_timeout_seconds=0.001,
    )
    server = SimpleNamespace(should_exit=False, force_exit=False)
    host._server = server
    finished = threading.Event()

    def linger_past_grace() -> None:
        time.sleep(0.05)
        finished.set()

    thread = threading.Thread(target=linger_past_grace, daemon=False)
    host._thread = thread
    thread.start()

    started = time.monotonic()
    host._retire_server_thread()

    assert time.monotonic() - started >= 0.04
    assert finished.is_set() is True
    assert thread.is_alive() is False
    assert server.should_exit is True
    assert server.force_exit is True


def test_chrome_once_waits_for_exact_public_resolution_events(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        effective_config=_chrome_effective_config(),
        approval_mode="chrome-once",
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.0,
    )
    operation_digest = _digest("browser-operation")
    pending = {
        "approval_id": "approval_browser_001",
        "operation": {
            "operation_id": "operation_browser_001",
            "operation_digest": operation_digest,
            "sandbox_workspace_id": "sandbox_workspace_browser_001",
        },
        "sandbox_run": {
            "sandbox_run_id": "sandbox_run_browser_001",
            "sandbox_workspace_id": "sandbox_workspace_browser_001",
        },
    }
    pre_workspace = {
        "pending_approvals": [pending],
        "scientific_evidence": {
            "operations": [
                {
                    "operation_id": "operation_browser_001",
                    "operation_digest": operation_digest,
                    "approval_id": "approval_browser_001",
                    "approval_state": "pending",
                    "status": "waiting_approval",
                }
            ]
        },
    }
    post_workspace = {
        "pending_approvals": [],
        "scientific_evidence": {
            "operations": [
                {
                    "operation_id": "operation_browser_001",
                    "operation_digest": operation_digest,
                    "approval_id": "approval_browser_001",
                    "approval_state": "approved",
                    "status": "waiting_approval",
                }
            ]
        },
    }
    resolution_events = (
        {
            "cursor": 11,
            "event_id": "event_browser_resolved",
            "session_id": "sess_browser_001",
            "event_type": "approval.resolved",
            "schema_version": "openzyme.v3.event.v1",
            "visibility": "public",
            "actor_ref": "local-user",
            "command_id": "command_browser_resolved",
            "created_at": "2026-07-18T00:00:00+00:00",
            "payload": {
                "approval_id": "approval_browser_001",
                "decision": "approved",
                "actor_ref": "local-user",
            },
        },
        {
            "cursor": 12,
            "event_id": "event_browser_continuation",
            "session_id": "sess_browser_001",
            "event_type": "sdk_controlled_operation.approval_resolved",
            "schema_version": "openzyme.v3.event.v1",
            "visibility": "public",
            "actor_ref": None,
            "command_id": "command_browser_continuation",
            "created_at": "2026-07-18T00:00:01+00:00",
            "payload": {
                "approval_id": "approval_browser_001",
                "operation_id": "operation_browser_001",
                "operation_digest": operation_digest,
                "continuation_id": "continuation_browser_001",
                "decision": "approved",
            },
        },
    )

    workspace_receipt = _public_receipt(
        sequence=1,
        route="/v3/sessions/sess_browser_001/workspace",
        semantic_value=pre_workspace,
    )

    class Api(_ReceiptAwareFake):
        base_url = "http://127.0.0.1:54321"
        response_binding = staticmethod(live._PublicHostClient.response_binding)

        def __init__(self) -> None:
            super().__init__((workspace_receipt,))
            self.event_reads = 0

        def get_event_records(
            self,
            session_id: str,
            *,
            after_cursor: int = 0,
            _timeout_seconds: float | None = None,
        ) -> tuple[dict[str, object], ...]:
            del _timeout_seconds
            assert session_id == "sess_browser_001"
            assert after_cursor == 10
            self.event_reads += 1
            self._append_receipt(
                _public_receipt(
                    sequence=len(self.receipts) + 1,
                    route=(
                        "/v3/sessions/sess_browser_001/events"
                        "?replay=1&after_cursor=10"
                    ),
                    semantic_value=list(resolution_events),
                )
            )
            return resolution_events

        def get_json(
            self,
            route: str,
            *,
            _timeout_seconds: float | None = None,
        ) -> dict[str, object]:
            del _timeout_seconds
            assert route == "/v3/sessions/sess_browser_001/workspace"
            self._append_receipt(
                _public_receipt(
                    sequence=len(self.receipts) + 1,
                    route=route,
                    semantic_value=post_workspace,
                )
            )
            return post_workspace

    api = Api()
    receipt, workspace = runner._wait_for_browser_approval(
        api,  # type: ignore[arg-type]
        session_id="sess_browser_001",
        workspace=pre_workspace,
        workspace_receipt=workspace_receipt,
        pending_approval=pending,
        started=time.monotonic(),
        pre_event_cursor=10,
    )

    assert workspace == post_workspace
    assert receipt["operation_digest"] == operation_digest
    assert receipt["driver_resolve_route_absent"] is True
    assert receipt["resolution_event_cursor"] == 11
    assert receipt["continuation_event_cursor"] == 12
    operator_output = capsys.readouterr().err
    assert '"status": "approval_required"' in operator_output
    assert '"status": "approval_observed"' in operator_output
    handoff = next(
        json.loads(line)
        for line in operator_output.splitlines()
        if '"status": "approval_required"' in line
    )
    assert handoff["sealed_page_url"] == live.BROWSER_SEALED_PAGE_URL
    assert handoff["served_ui_dist_digest"] == _digest("built-ui-dist")
    assert (
        handoff["browser_observation_receipt_schema_id"]
        == live.BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID
    )


def test_chrome_once_rejects_continuation_operation_identity_drift(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        effective_config=_chrome_effective_config(),
        approval_mode="chrome-once",
        timeout_seconds=0.01,
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.0,
    )
    operation_digest = _digest("browser-operation")
    pending = {
        "approval_id": "approval_browser_001",
        "operation": {
            "operation_id": "operation_browser_001",
            "operation_digest": operation_digest,
            "sandbox_workspace_id": "sandbox_workspace_browser_001",
        },
        "sandbox_run": {
            "sandbox_run_id": "sandbox_run_browser_001",
        },
    }
    pre_workspace = {"pending_approvals": [pending]}

    workspace_receipt = _public_receipt(
        sequence=1,
        route="/v3/sessions/sess_browser_001/workspace",
        semantic_value=pre_workspace,
    )

    class Api(_ReceiptAwareFake):
        base_url = "http://127.0.0.1:54321"
        response_binding = staticmethod(live._PublicHostClient.response_binding)

        def __init__(self) -> None:
            super().__init__((workspace_receipt,))
            self.event_reads = 0

        def get_event_records(
            self,
            session_id: str,
            *,
            after_cursor: int = 0,
            _timeout_seconds: float | None = None,
        ) -> tuple[dict[str, object], ...]:
            del _timeout_seconds
            assert session_id == "sess_browser_001"
            self.event_reads += 1
            if self.event_reads == 1:
                records: tuple[dict[str, object], ...] = ()
            else:
                records = (
                {
                    "cursor": 1,
                    "event_id": "event_resolved",
                    "event_type": "approval.resolved",
                    "payload": {
                        "approval_id": "approval_browser_001",
                        "decision": "approved",
                        "actor_ref": "local-user",
                    },
                },
                {
                    "cursor": 2,
                    "event_id": "event_continuation",
                    "event_type": "sdk_controlled_operation.approval_resolved",
                    "payload": {
                        "approval_id": "approval_browser_001",
                        "operation_id": "operation_browser_001",
                        "operation_digest": _digest("drift"),
                        "continuation_id": "continuation_browser_001",
                        "decision": "approved",
                    },
                    },
                )
            self._append_receipt(
                _public_receipt(
                    sequence=len(self.receipts) + 1,
                    route=(
                        "/v3/sessions/sess_browser_001/events"
                        f"?replay=1&after_cursor={after_cursor}"
                    ),
                    semantic_value=list(records),
                )
            )
            return records

    api = Api()
    with pytest.raises(live.LiveProductPathError) as error:
        runner._wait_for_browser_approval(
            api,  # type: ignore[arg-type]
            session_id="sess_browser_001",
            workspace=pre_workspace,
            workspace_receipt=workspace_receipt,
            pending_approval=pending,
            started=time.monotonic(),
            pre_event_cursor=0,
        )

    assert error.value.code == "browser_approval_operation_identity_drift"


def test_chrome_once_uses_independent_handoff_timeout(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        effective_config=_chrome_effective_config(),
        approval_mode="chrome-once",
        timeout_seconds=60.0,
        browser_approval_timeout_seconds=0.005,
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.0,
    )
    operation_digest = _digest("browser-operation-timeout")
    pending = {
        "approval_id": "approval_browser_timeout",
        "operation": {
            "operation_id": "operation_browser_timeout",
            "operation_digest": operation_digest,
            "sandbox_workspace_id": "sandbox_workspace_browser_timeout",
        },
        "sandbox_run": {
            "sandbox_run_id": "sandbox_run_browser_timeout",
        },
    }
    pre_workspace = {"pending_approvals": [pending]}

    workspace_receipt = _public_receipt(
        sequence=1,
        route="/v3/sessions/sess_browser_timeout/workspace",
        semantic_value=pre_workspace,
    )

    class Api(_ReceiptAwareFake):
        base_url = "http://127.0.0.1:54321"
        response_binding = staticmethod(live._PublicHostClient.response_binding)

        def __init__(self) -> None:
            super().__init__((workspace_receipt,))

        def get_event_records(
            self,
            session_id: str,
            *,
            after_cursor: int = 0,
            _timeout_seconds: float | None = None,
        ) -> tuple[dict[str, object], ...]:
            del _timeout_seconds
            assert session_id == "sess_browser_timeout"
            assert after_cursor == 7
            self._append_receipt(
                _public_receipt(
                    sequence=len(self.receipts) + 1,
                    route=(
                        "/v3/sessions/sess_browser_timeout/events"
                        "?replay=1&after_cursor=7"
                    ),
                    semantic_value=[],
                )
            )
            return ()

    api = Api()
    started = time.monotonic()
    with pytest.raises(live.LiveProductPathError) as error:
        runner._wait_for_browser_approval(
            api,  # type: ignore[arg-type]
            session_id="sess_browser_timeout",
            workspace=pre_workspace,
            workspace_receipt=workspace_receipt,
            pending_approval=pending,
            started=started,
            pre_event_cursor=7,
        )

    assert error.value.code == "browser_approval_timeout"
    assert time.monotonic() - started < 1.0


def test_chrome_once_gate_is_scoped_to_positive_one(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        approval_mode="chrome-once",
        browser_completion_hold_seconds=0.0,
    )
    campaign_root = tmp_path / "campaign"
    contexts = []
    for attempt_number, attempt_kind in (
        (1, "positive"),
        (2, "positive"),
        (3, "fault"),
    ):
        roots = create_blank_world_roots(
            campaign_root,
            attempt_kind=attempt_kind,
            allowed_prerequisites=_allowed_prerequisites(),
        )
        contexts.append(
            AttemptRunContext(
                roots=roots,
                identity=_identity(),
                ledger_before=safe_micu_ledger_snapshot(ledger_path),
                attempt_number=attempt_number,
            )
        )

    assert [runner._browser_gate_enabled(context) for context in contexts] == [
        True,
        False,
        False,
    ]
    assert runner._settings_blocker(contexts[0]) == {
        "code": "browser_observation_receipt_path_missing",
        "message": "chrome-once requires a fresh observation receipt target before campaign start",
    }

    receipt_path = tmp_path / "browser-observation.json"
    receipt_path.write_text("{}", encoding="utf-8")
    runner.browser_observation_receipt_path = receipt_path
    assert runner._settings_blocker(contexts[0]) == {
        "code": "browser_observation_receipt_path_invalid",
        "message": "Chrome observation target must be absent under an existing writable non-symlink directory",
    }
    assert all(
        (runner._settings_blocker(context) or {}).get("code")
        != "browser_observation_receipt_path_invalid"
        for context in contexts[1:]
    )


def test_chrome_observation_rejects_receipt_written_before_hold_end(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "browser-observation.json"
    receipt_path.write_text("{}", encoding="utf-8")
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(tmp_path / "ledger.sqlite3"),
        ledger_path=tmp_path / "ledger.sqlite3",
        approval_mode="chrome-once",
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.05,
        browser_observation_receipt_path=receipt_path,
    )
    operation_digest = _digest("browser-observation-operation")
    approval = {
        "approval_id": "approval_observation_001",
        "operation_id": "operation_observation_001",
        "operation_digest": operation_digest,
    }
    formal = live.SessionDriveResult(
        session_id="sess_observation_001",
        purpose="formal",
        state="completed",
        blocker_code=None,
        workspace={
            "pending_approvals": [],
            "conversation": [
                {
                    "message_id": "msg_observation_final",
                    "role": "assistant",
                    "content": "completed",
                }
            ],
            "reports": [
                {"report_id": "report_observation_001", "status": "published"}
            ],
            "scientific_evidence": {
                "operations": [
                    {
                        "operation_id": "operation_observation_001",
                        "operation_digest": operation_digest,
                        "status": "completed",
                    }
                ]
            },
        },
        workspace_response_binding={},
        event_receipt={},
        drain_count=1,
        approval_ids=("approval_observation_001",),
        browser_approval_receipt=approval,
    )
    ready_started = time.monotonic()

    with pytest.raises(live.LiveProductPathError) as error:
        runner._wait_for_browser_observation(
            formal,
            observation_ready_started=ready_started,
            observation_ready_wall_ns=time.time_ns(),
        )

    assert error.value.code == "browser_observation_receipt_too_early"


def test_positive_blocker_preserves_formal_failure_before_browser_gate(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    provider = SQLiteRepositoryProvider(str(tmp_path / "blank.sqlite3"))
    failed_formal = live.SessionDriveResult(
        session_id="sess_formal_failed",
        purpose="formal",
        state="failed",
        blocker_code="workflow_ref_not_authorized",
        workspace={},
        workspace_response_binding={},
        event_receipt={},
        drain_count=1,
        approval_ids=(),
    )

    assert runner._positive_blocker(
        provider,
        failed_formal,
        browser_gate_required=True,
    ) == {
        "code": "workflow_ref_not_authorized",
        "message": "formal product path did not reach its published-report exit",
    }

    completed_without_browser = replace(
        failed_formal,
        state="completed",
        blocker_code=None,
    )
    assert runner._positive_blocker(
        provider,
        completed_without_browser,
        browser_gate_required=True,
    ) == {
        "code": "browser_approval_not_observed",
        "message": (
            "first positive formal path did not preserve a Chrome-observed "
            "same-operation approval receipt"
        ),
    }


def test_chrome_observation_uses_independent_submission_timeout(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "browser-observation.json"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(tmp_path / "ledger.sqlite3"),
        ledger_path=tmp_path / "ledger.sqlite3",
        effective_config=_chrome_effective_config(),
        approval_mode="chrome-once",
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.0,
        browser_observation_submission_timeout_seconds=0.005,
        browser_observation_receipt_path=receipt_path,
    )
    operation_digest = _digest("browser-observation-timeout")
    formal = live.SessionDriveResult(
        session_id="sess_observation_timeout",
        purpose="formal",
        state="completed",
        blocker_code=None,
        workspace={
            "pending_approvals": [],
            "conversation": [
                {
                    "message_id": "msg_observation_timeout_final",
                    "role": "assistant",
                    "content": "completed",
                }
            ],
            "reports": [
                {"report_id": "report_observation_timeout", "status": "published"}
            ],
            "scientific_evidence": {
                "operations": [
                    {
                        "operation_id": "operation_observation_timeout",
                        "operation_digest": operation_digest,
                        "status": "completed",
                    }
                ]
            },
        },
        workspace_response_binding={},
        event_receipt={},
        drain_count=1,
        approval_ids=("approval_observation_timeout",),
        browser_approval_receipt={
            "approval_id": "approval_observation_timeout",
            "operation_id": "operation_observation_timeout",
            "operation_digest": operation_digest,
        },
    )
    started = time.monotonic()

    with pytest.raises(live.LiveProductPathError) as error:
        runner._wait_for_browser_observation(
            formal,
            observation_ready_started=started,
            observation_ready_wall_ns=time.time_ns(),
        )

    assert error.value.code == "browser_observation_receipt_missing"
    assert time.monotonic() - started < 0.5


def test_chrome_observation_accepts_stable_post_hold_receipt(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "browser-observation.json"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(tmp_path / "ledger.sqlite3"),
        ledger_path=tmp_path / "ledger.sqlite3",
        effective_config=_chrome_effective_config(),
        approval_mode="chrome-once",
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.01,
        browser_observation_submission_timeout_seconds=1.0,
        browser_observation_receipt_path=receipt_path,
    )
    operation_digest = _digest("browser-observation-valid")
    approval = {
        "approval_id": "approval_observation_valid",
        "operation_id": "operation_observation_valid",
        "operation_digest": operation_digest,
        "observation_challenge": _digest("browser-challenge"),
        "page_url": live.BROWSER_SEALED_PAGE_URL,
        "host_process_id": os.getpid(),
        "served_ui_dist_digest": _digest("built-ui-dist"),
    }
    formal = live.SessionDriveResult(
        session_id="sess_observation_valid",
        purpose="formal",
        state="completed",
        blocker_code=None,
        workspace={
            "pending_approvals": [],
            "conversation": [
                {
                    "message_id": "msg_observation_valid_final",
                    "role": "assistant",
                    "content": "completed",
                }
            ],
            "reports": [
                {"report_id": "report_observation_valid", "status": "published"}
            ],
            "scientific_evidence": {
                "operations": [
                    {
                        "operation_id": "operation_observation_valid",
                        "operation_digest": operation_digest,
                        "status": "completed",
                    }
                ]
            },
        },
        workspace_response_binding={"sequence": 7},
        event_receipt={
            "event_stream_digest": _digest("browser-events"),
            "last_cursor": 9,
            "public_response_binding": {"sequence": 8},
        },
        drain_count=1,
        approval_ids=("approval_observation_valid",),
        browser_approval_receipt=approval,
    )
    page_target_id = "chrome-page-1"
    page_state = live._terminal_browser_page_state(formal)
    transcript = [
        {
            "sequence": sequence,
            "tool": "chrome_devtools_mcp",
            "method": method,
            "page_target_id": page_target_id,
            "request_digest": _digest(f"request-{method}"),
            "response_digest": _digest(f"response-{method}"),
        }
        for sequence, method in enumerate(
            ("list_console_messages", "evaluate_script", "take_screenshot"),
            start=1,
        )
    ]
    screenshot_base64 = _one_pixel_grayscale_png(filter_byte=0)
    screenshot_bytes = base64.b64decode(screenshot_base64)
    command_id = "chrome-observation-valid"
    command_digest = live.canonical_digest(
        {
            "tool": "chrome_devtools_mcp",
            "command_id": command_id,
            "page_target_id": page_target_id,
            "observation_challenge": approval["observation_challenge"],
            "action": "observe_console_page_state_and_screenshot",
        }
    )
    screenshot_digest = live._sha256(screenshot_bytes)
    response_digest = live.canonical_digest(
        {
            "page_state": page_state,
            "console_entries": [],
            "application_error_count": 0,
            "devtools_transcript_digest": live.canonical_digest(transcript),
            "screenshot_digest": screenshot_digest,
        }
    )
    receipt_path.write_text(
        json.dumps(
            {
                "schema_id": live.BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID,
                "observation_mode": live.BROWSER_OBSERVATION_MODE,
                "observation_challenge": approval["observation_challenge"],
                "session_id": formal.session_id,
                "approval_id": approval["approval_id"],
                "operation_id": approval["operation_id"],
                "page_url": approval["page_url"],
                "host_process_id": approval["host_process_id"],
                "served_ui_dist_digest": approval["served_ui_dist_digest"],
                "page_target_id": page_target_id,
                "observation_window_seconds": 0.01,
                "console_entries": [],
                "console_entries_digest": live.canonical_digest([]),
                "application_error_count": 0,
                "page_state": page_state,
                "page_state_digest": live.canonical_digest(page_state),
                "devtools_command_receipt": {
                    "command_id": command_id,
                    "tool": "chrome_devtools_mcp",
                    "command_digest": command_digest,
                    "response_digest": response_digest,
                    "page_target_id": page_target_id,
                },
                "devtools_transcript": transcript,
                "devtools_transcript_digest": live.canonical_digest(transcript),
                "screenshot_png_base64": screenshot_base64,
                "screenshot_digest": screenshot_digest,
                "screenshot_width": 1,
                "screenshot_height": 1,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    receipt = runner._wait_for_browser_observation(
        formal,
        observation_ready_started=time.monotonic() - 0.02,
        observation_ready_wall_ns=(
            receipt_path.stat().st_mtime_ns - 20_000_000
        ),
    )

    assert receipt["host_observation_hold_satisfied"] is True
    assert receipt["host_observation_submission_timeout_seconds"] == 1.0
    assert receipt["screenshot_digest"] == screenshot_digest


@pytest.mark.parametrize(
    ("filter_byte", "trailing_zlib_bytes", "valid"),
    ((0, b"", True), (5, b"", False), (0, b"trailing", False)),
)
def test_browser_png_validation_is_decodable_and_bounded(
    filter_byte: int,
    trailing_zlib_bytes: bytes,
    valid: bool,
) -> None:
    encoded = _one_pixel_grayscale_png(
        filter_byte=filter_byte,
        trailing_zlib_bytes=trailing_zlib_bytes,
    )

    assert (live._browser_screenshot_png(encoded) is not None) is valid
    assert (cutover_evidence._validated_browser_png(encoded) is not None) is valid


def test_cli_exposes_chrome_once_mode(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "run-live",
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--identity",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites",
            str(tmp_path / "prerequisites.json"),
            "--approval-mode",
            "chrome-once",
            "--browser-completion-hold-seconds",
            "0",
            "--browser-approval-timeout-seconds",
            "12",
        ]
    )

    assert args.approval_mode == "chrome-once"
    assert args.browser_completion_hold_seconds == 0.0
    assert args.browser_approval_timeout_seconds == 12.0
