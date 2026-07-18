from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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
from openzyme_runtime import OpenZymeSettings


def _digest(label: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


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
        "toolchain_id": "mafft@7.526",
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
        toolchain_id="mafft@7.526",
        input_artifact_ids=("art_input",),
        stage_refs=tuple(material["stage_refs"]),
        planned_fetch_intent=dict(material["planned_fetch_intent"]),
        approval_requirement={"required": True},
        adapter_result_envelope={"backend_run_id": "job_001"},
        expected_outputs_summary=dict(material["expected_outputs"]),
        resource_estimate=dict(material["resource_estimate"]),
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
        allowed_prerequisites={},
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

    monkeypatch.setattr(live.LiveAoxAttemptRunner, "_settings_blocker", lambda self: None)
    monkeypatch.setattr(live, "build_configured_foundation", lambda **kwargs: object())
    monkeypatch.setattr(live, "create_app", lambda dependencies: object())
    monkeypatch.setattr(live, "TestClient", lambda app: Client())
    monkeypatch.setattr(live.LiveAoxAttemptRunner, "_run_session", stop_at_first_session)
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
        allowed_prerequisites={},
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
        allowed_prerequisites={},
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
