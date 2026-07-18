from __future__ import annotations

import base64
from dataclasses import replace
import os
from pathlib import Path
import struct
import time
import zlib

from fastapi import FastAPI
import pytest

from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationStatus
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
    monkeypatch.setattr(live, "TestClient", lambda app: Client())
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner, "_run_session", stop_at_first_session
    )
    runner = live.LiveAoxAttemptRunner(settings=settings, ledger_path=ledger_path)

    evidence = runner(context)

    assert observed["registered_before_session"] is True
    assert evidence["scientific_outcome"]["blocker_code"] == "test_stop"


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


def test_chrome_once_waits_for_exact_public_resolution_events(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
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

    class Api:
        base_url = "http://127.0.0.1:54321"
        receipts: list[live.PublicApiReceipt] = [
            _public_receipt(
                sequence=1,
                route="/v3/sessions/sess_browser_001/workspace",
                semantic_value=pre_workspace,
            )
        ]
        event_reads = 0
        response_binding = staticmethod(live._PublicHostClient.response_binding)

        @classmethod
        def get_event_records(
            cls,
            session_id: str,
            *,
            after_cursor: int = 0,
        ) -> tuple[dict[str, object], ...]:
            assert session_id == "sess_browser_001"
            assert after_cursor == 10
            cls.event_reads += 1
            cls.receipts.append(
                _public_receipt(
                    sequence=len(cls.receipts) + 1,
                    route=(
                        "/v3/sessions/sess_browser_001/events"
                        "?replay=1&after_cursor=10"
                    ),
                    semantic_value=list(resolution_events),
                )
            )
            return resolution_events

        @classmethod
        def get_json(cls, route: str) -> dict[str, object]:
            assert route == "/v3/sessions/sess_browser_001/workspace"
            cls.receipts.append(
                _public_receipt(
                    sequence=len(cls.receipts) + 1,
                    route=route,
                    semantic_value=post_workspace,
                )
            )
            return post_workspace

    receipt, workspace = runner._wait_for_browser_approval(
        Api(),  # type: ignore[arg-type]
        session_id="sess_browser_001",
        workspace=pre_workspace,
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


def test_chrome_once_rejects_continuation_operation_identity_drift(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
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

    class Api:
        base_url = "http://127.0.0.1:54321"
        receipts: list[live.PublicApiReceipt] = [
            _public_receipt(
                sequence=1,
                route="/v3/sessions/sess_browser_001/workspace",
                semantic_value=pre_workspace,
            )
        ]
        event_reads = 0
        response_binding = staticmethod(live._PublicHostClient.response_binding)

        @classmethod
        def get_event_records(
            cls,
            session_id: str,
            *,
            after_cursor: int = 0,
        ) -> tuple[dict[str, object], ...]:
            assert session_id == "sess_browser_001"
            cls.event_reads += 1
            if cls.event_reads == 1:
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
            cls.receipts.append(
                _public_receipt(
                    sequence=len(cls.receipts) + 1,
                    route=(
                        "/v3/sessions/sess_browser_001/events"
                        f"?replay=1&after_cursor={after_cursor}"
                    ),
                    semantic_value=list(records),
                )
            )
            return records

    with pytest.raises(live.LiveProductPathError) as error:
        runner._wait_for_browser_approval(
            Api(),  # type: ignore[arg-type]
            session_id="sess_browser_001",
            workspace=pre_workspace,
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

    class Api:
        base_url = "http://127.0.0.1:54321"
        receipts: list[live.PublicApiReceipt] = [
            _public_receipt(
                sequence=1,
                route="/v3/sessions/sess_browser_timeout/workspace",
                semantic_value=pre_workspace,
            )
        ]
        response_binding = staticmethod(live._PublicHostClient.response_binding)

        @classmethod
        def get_event_records(
            cls,
            session_id: str,
            *,
            after_cursor: int = 0,
        ) -> tuple[dict[str, object], ...]:
            assert session_id == "sess_browser_timeout"
            assert after_cursor == 7
            cls.receipts.append(
                _public_receipt(
                    sequence=len(cls.receipts) + 1,
                    route=(
                        "/v3/sessions/sess_browser_timeout/events"
                        "?replay=1&after_cursor=7"
                    ),
                    semantic_value=[],
                )
            )
            return ()

    started = time.monotonic()
    with pytest.raises(live.LiveProductPathError) as error:
        runner._wait_for_browser_approval(
            Api(),  # type: ignore[arg-type]
            session_id="sess_browser_timeout",
            workspace=pre_workspace,
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
