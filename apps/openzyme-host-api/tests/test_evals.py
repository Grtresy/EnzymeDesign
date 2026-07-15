from __future__ import annotations

import subprocess

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionStatus
from openzyme_host_api.evals import S15_AOX_HMM_FIXED_DELIVERABLES
from openzyme_host_api.evals import S15_AOX_HMM_FIXTURE_SCENARIO_ID
from openzyme_host_api.evals import S15_AOX_HMM_OLD_DELIVERABLES
from openzyme_host_api.evals import S15_AOX_HMM_SCENARIO_ID
from openzyme_host_api.evals import S15_ROUTE_POLICY_IDS
from openzyme_host_api.evals import AOX_HMM_ACCESSIONS
from openzyme_host_api.evals import _s15_aox_validate_final_artifacts
from openzyme_host_api.evals import _s15_bootstrap_live_sandbox_image
from openzyme_host_api.evals import _s15_build_evidence_bundle
from openzyme_host_api.evals import _s15_event_text_has_legacy_execution_pipeline
from openzyme_host_api.evals import _s15_live_prerequisite_report
from openzyme_host_api.evals import _s15_live_workspace_ready
from openzyme_host_api.evals import _run_v3_aox_hmm_prompt_scenario
from openzyme_host_api.evals import _s15_validate_evidence_bundle
from openzyme_host_api.evals import _s15_validate_live_product_path
from openzyme_host_api.evals import build_local_eval_runtime
from openzyme_host_api.evals import run_v3_local_evals
from openzyme_host_api.evals import run_v3_s15_live_evals
from openzyme_runtime import reset_settings_cache


@pytest.fixture(scope="module")
def local_eval_summary() -> dict[str, object]:
    return run_v3_local_evals(upload_results=False)


def test_v3_local_eval_covers_cutover_design_path(local_eval_summary: dict[str, object]) -> None:
    summary = local_eval_summary
    assert summary["scenario_count"] == 2
    assert summary["failed"] == 0
    result = next(item for item in summary["results"] if item["scenario_id"] == "v3_design_cutover_path")
    assert result["scenario_id"] == "v3_design_cutover_path"
    assert result["task_count"] == 3
    assert set(result["agent_roles"]) >= {"researcher", "executor", "reporter"}
    assert set(result["capability_keys"]) >= {"deep_research", "execution"}
    assert result["report_count"] == 1
    assert all(result["checks"].values())


def test_v3_local_eval_covers_aox_hmm_prompt_e2e(local_eval_summary: dict[str, object]) -> None:
    summary = local_eval_summary
    result = next(item for item in summary["results"] if item["scenario_id"] == S15_AOX_HMM_FIXTURE_SCENARIO_ID)
    assert result["scenario_class"] == "fixture"
    assert result["status"] == "passed"
    assert result["live_cutover_eligible"] is False
    assert result["task_count"] == 1
    assert result["candidate_count"] == 5
    assert set(result["required_artifacts"]) == S15_AOX_HMM_FIXED_DELIVERABLES
    assert result["legacy_artifacts"] == []
    assert result["final_output_validation"]["passed"] is False
    assert result["checks"]["final_output_validation"] is False
    assert not (S15_AOX_HMM_OLD_DELIVERABLES & set(result["required_artifacts"]))
    fixture_control_checks = {
        key: value
        for key, value in result["checks"].items()
        if key
        not in {
            "required_artifacts",
            "candidate85_artifact",
            "final_output_validation",
            "evidence_bundle_complete",
        }
    }
    assert all(fixture_control_checks.values())


def test_s15_final_output_validator_rejects_legacy_only_outputs() -> None:
    legacy_only = set(S15_AOX_HMM_OLD_DELIVERABLES)

    validation = _s15_aox_validate_final_artifacts(legacy_only, {})

    assert validation["passed"] is False
    error_codes = {error["error_code"] for error in validation["errors"]}
    assert "live_artifact_missing" in error_codes
    assert "legacy_artifact_path_forbidden" in error_codes
    assert validation["legacy_paths"] == sorted(S15_AOX_HMM_OLD_DELIVERABLES)


def test_s15_final_output_validator_enforces_fixed_thresholds_and_provenance() -> None:
    valid_text = {
        "aox_hmm/AOX_ref21.fasta": ">AAC72747.1\nMSEQ\n",
        "aox_hmm/target.fasta": "",
        "aox_hmm/AOX_ref.hmm": "HMMER3/f [aox]\nNAME AOX_ref\n//\n",
        "aox_hmm/hits_raw.csv": "target,uniprot_accession,hmm_score,evalue,length\n",
        "aox_hmm/hits_len650_700_200.csv": "target,uniprot_accession,hmm_score,evalue,length,sequence\n",
        "aox_hmm/scored_ref_plus_hits.csv": "id,seq_score,pass_rule,activity_score,reference_coordinate\n",
        "aox_hmm/AOX_candidates.fasta": ">candidate\nMSEQ\n",
        "aox_hmm/AOX_candidates_cdhit85.fasta": ">candidate\nMSEQ\n",
        "aox_hmm/nodes.csv": "node_id,label,score,cluster_id\n",
        "aox_hmm/edges_similarity.csv": "source,target,similarity\n",
        "aox_hmm/execution_summary.json": (
            "{"
            '"accession_count": 13,'
            '"candidate_count": 1,'
            '"length_filter": [650, 700],'
            '"hmm_score_threshold": 200,'
            '"activity_score_threshold": 33.6,'
            '"similarity_threshold": 0.85,'
            '"hmmer_database": "refprot",'
            '"provider_status": "ok",'
            '"tool_status": "ok",'
            '"warning_count": 1,'
            '"artifact_ids": ["artifact_1"],'
            f'"normalized_final_deliverable_paths": {sorted(S15_AOX_HMM_FIXED_DELIVERABLES)!r}'.replace("'", '"')
            + "}"
        ),
    }
    valid_metadata = {
        "aox_hmm/AOX_ref21.fasta": {
            "accession_count": len(AOX_HMM_ACCESSIONS),
            "provider_request_ids": ["provider_req_1"],
        },
        "aox_hmm/AOX_ref.hmm": {
            "source_reference_fasta_artifact_id": "artifact_ref",
            "mafft_artifact_ids": ["artifact_alignment"],
            "hmmbuild_artifact_ids": ["artifact_hmm"],
        },
    }

    accepted = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        valid_text,
        valid_metadata,
    )
    broken_text = dict(valid_text)
    broken_text["aox_hmm/scored_ref_plus_hits.csv"] = "id,seq_score,pass_rule\n"
    broken_text["aox_hmm/execution_summary.json"] = valid_text["aox_hmm/execution_summary.json"].replace(
        '"refprot"',
        '"nr"',
    )
    broken_metadata = {
        "aox_hmm/AOX_ref21.fasta": {"accession_count": 12},
        "aox_hmm/AOX_ref.hmm": {"source_reference_fasta_artifact_id": "artifact_ref"},
    }

    rejected = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        broken_text,
        broken_metadata,
    )

    assert accepted["passed"] is True
    error_codes = {error["error_code"] for error in rejected["errors"]}
    assert rejected["passed"] is False
    assert {
        "invalid_csv_columns",
        "invalid_execution_summary_value",
        "invalid_accession_count",
        "provider_provenance_incomplete",
        "hmm_provenance_incomplete",
    } <= error_codes


def test_s15_final_output_validator_requires_empty_target_warning() -> None:
    text = {
        path: "placeholder\n"
        for path in S15_AOX_HMM_FIXED_DELIVERABLES
    }
    text.update(
        {
            "aox_hmm/AOX_ref21.fasta": ">AAC72747.1\nMSEQ\n",
            "aox_hmm/target.fasta": "",
            "aox_hmm/AOX_ref.hmm": "HMMER3/f [aox]\nNAME AOX_ref\n//\n",
            "aox_hmm/hits_raw.csv": "target,uniprot_accession,hmm_score,evalue,length\n",
            "aox_hmm/hits_len650_700_200.csv": "target,uniprot_accession,hmm_score,evalue,length,sequence\n",
            "aox_hmm/scored_ref_plus_hits.csv": "id,seq_score,pass_rule,activity_score,reference_coordinate\n",
            "aox_hmm/AOX_candidates.fasta": ">candidate\nMSEQ\n",
            "aox_hmm/AOX_candidates_cdhit85.fasta": ">candidate\nMSEQ\n",
            "aox_hmm/nodes.csv": "node_id,label,score,cluster_id\n",
            "aox_hmm/edges_similarity.csv": "source,target,similarity\n",
            "aox_hmm/execution_summary.json": (
                "{"
                '"accession_count": 13,'
                '"candidate_count": 1,'
                '"length_filter": [650, 700],'
                '"hmm_score_threshold": 200,'
                '"activity_score_threshold": 33.6,'
                '"similarity_threshold": 0.85,'
                '"hmmer_database": "refprot",'
                '"provider_status": "ok",'
                '"tool_status": "ok",'
                '"warning_count": 0,'
                '"artifact_ids": ["artifact_1"],'
                f'"normalized_final_deliverable_paths": {sorted(S15_AOX_HMM_FIXED_DELIVERABLES)!r}'.replace("'", '"')
                + "}"
            ),
        }
    )
    metadata = {
        "aox_hmm/AOX_ref21.fasta": {
            "accession_count": len(AOX_HMM_ACCESSIONS),
            "provider_request_ids": ["provider_req_1"],
        },
        "aox_hmm/AOX_ref.hmm": {
            "source_reference_fasta_artifact_id": "artifact_ref",
            "mafft_artifact_ids": ["artifact_alignment"],
            "hmmbuild_artifact_ids": ["artifact_hmm"],
        },
    }

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    assert validation["passed"] is False
    assert {"error_code": "empty_target_warning_missing", "path": "aox_hmm/target.fasta"} in validation["errors"]


def test_s15_evidence_bundle_rejects_summary_only_payload() -> None:
    validation = _s15_validate_evidence_bundle(
        {
            "fixed_prompt_digest": "sha256:prompt",
            "session_id": "sess_eval_aox_hmm",
            "registered_artifact_ids": ["artifact_1"],
            "normalized_final_deliverable_paths": sorted(S15_AOX_HMM_FIXED_DELIVERABLES),
            "final_answer_available": True,
        }
    )

    assert validation["passed"] is False
    missing = set(validation["missing_fields"])
    assert {
        "approval_ids",
        "operation_trace",
        "sandbox_workspace_id",
        "sandbox_image_digests",
        "source_snapshot_digests",
        "route_policy_ids",
        "toolchain_ids",
        "provider_config_digests",
        "backend_run_ids",
        "final_answer_digest",
    } <= missing


def test_s15_evidence_bundle_rejects_approval_bridge_only_operation() -> None:
    evidence = {
        "fixed_prompt_digest": "sha256:prompt",
        "config_snapshot_digest": "sha256:config",
        "session_id": "sess_eval_aox_hmm",
        "sandbox_workspace_id": "sbx_s15",
        "sandbox_image_digests": ["sha256:image"],
        "adapter_schema_versions": ["s12.adapter_envelope.v1"],
        "route_policy_ids": ["bio.ncbi_fetch_proteins.provider:v1"],
        "toolchain_ids": ["toolchain:v1"],
        "provider_config_digests": ["provider_config:ncbi:v1"],
        "approval_ids": ["approval_s15"],
        "operation_trace": [
            {
                "operation_id": "op_s15",
                "operation_digest": "sha256:operation",
                "approval_id": "approval_s15",
                "sandbox_workspace_id": "sbx_s15",
                "source_snapshot_artifact_id": "artifact_source",
                "source_snapshot_digest": "sha256:source",
                "route_policy_id": "bio.ncbi_fetch_proteins.provider:v1",
                "selected_backend": "provider_http",
            }
        ],
        "operation_digests": ["sha256:operation"],
        "source_snapshot_artifact_ids": ["artifact_source"],
        "source_snapshot_digests": ["sha256:source"],
        "backend_run_ids": [],
        "registered_artifact_ids": ["artifact_output"],
        "normalized_final_deliverable_paths": sorted(S15_AOX_HMM_FIXED_DELIVERABLES),
        "final_answer_digest": "sha256:answer",
    }

    validation = _s15_validate_evidence_bundle(evidence)

    assert validation["passed"] is False
    assert validation["missing_fields"] == ["backend_run_ids"]
    assert validation["errors"] == [
        {"error_code": "live_evidence_incomplete", "missing_fields": ["backend_run_ids"]}
    ]


def test_s15_evidence_bundle_collects_approval_operation_and_sandbox_records(tmp_path) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    now = "2026-05-31T00:00:00+00:00"
    session = Session(
        session_id="sess_s15_evidence",
        project_id="proj_001",
        title="S15 evidence",
        objective="Validate S15 evidence bundle.",
        status=SessionStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    repositories.sessions.save(session)
    repositories.agents.save(
        AgentMember(
            agent_id="agent_executor",
            session_id=session.session_id,
            lane_id=None,
            task_id=None,
            name="Executor",
            role="executor",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at=now,
            updated_at=now,
            member_id="member_executor",
        )
    )
    repositories.sandbox_workspaces.save(
        SandboxWorkspaceRecord(
            sandbox_workspace_id="sbx_s15",
            session_id=session.session_id,
            agent_member_id="member_executor",
            agent_id="agent_executor",
            status=SandboxWorkspaceStatus.READY,
            image_ref="localhost/openzyme-pipeline-sandbox:dev",
            image_digest="sha256:image",
            image_version="2026.05",
            sandbox_protocol_version="s09",
            image_compatibility=SandboxImageCompatibility.COMPATIBLE,
            manifest_version="1",
            created_at=now,
            last_attached_at=now,
            registered_artifact_ids=("artifact_hits",),
            source_code_artifact_ids=("artifact_source",),
        )
    )
    source_path = tmp_path / "aox_hmm.py"
    source_path.write_text("print('run aox/hmm')\n", encoding="utf-8")
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="artifact_source",
            session_id=session.session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.CODE,
            storage_uri=str(source_path),
            relative_path="src/aox_hmm.py",
            created_at=now,
            metadata={"semantic_type": "pipeline_source", "content_digest": "sha256:source"},
        )
    )
    repositories.sandbox_runs.save(
        SandboxRunRecord(
            sandbox_run_id="run_s15",
            session_id=session.session_id,
            sandbox_workspace_id="sbx_s15",
            agent_id="agent_executor",
            argv=("python", "src/aox_hmm.py"),
            argv_digest="sha256:argv",
            cwd="/workspace",
            env_digest="sha256:env",
            status=SandboxRunStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            source_snapshot_artifact_id="artifact_source",
            source_tree_digest="sha256:source",
            stdout_summary="registered AOX/HMM outputs",
            stderr_summary="",
            exit_code=0,
            duration_ms=1234,
            changed_files_summary={"created": ["aox_hmm/hits_raw.csv"]},
        )
    )
    repositories.approvals.save(
        ApprovalRequest(
            approval_id="approval_s15",
            session_id=session.session_id,
            task_id=None,
            lane_id=None,
            kind="sdk_controlled_operation",
            requested_action="Run AOX/HMM provider and HPC operations.",
            status=ApprovalRequestStatus.APPROVED,
            request_ref="request_ref",
            resolution_ref="resolution_ref",
            created_at=now,
            resolved_at=now,
        )
    )
    repositories.controlled_operations.save(
        ControlledOperation(
            operation_id="op_s15",
            session_id=session.session_id,
            sandbox_workspace_id="sbx_s15",
            sandbox_run_id="run_s15",
            logical_operation_key="bio.hmmer_search",
            operation_digest="sha256:operation",
            params_digest="sha256:params",
            backend_category="provider_http",
            status=ControlledOperationStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            approval_id="approval_s15",
            approval_state="approved",
            route_reason="static_policy:v1",
            source_snapshot_artifact_id="artifact_source",
            source_snapshot_digest="sha256:source",
            adapter_envelope_schema_version="s12.adapter_envelope.v1",
            sdk_module="bio",
            function_name="hmmer_search",
            route_policy_id="bio.hmmer_search.provider:v1",
            selected_backend="provider_http",
            runtime_packaging_id="provider_http.aox_hmm_2026_05_31",
            toolchain_id="ebi_hmmer_rest.refprot:v1",
            provider_config_digest="sha256:provider-config",
            expected_outputs_summary={"items": [{"path": "aox_hmm/hits_raw.csv"}]},
            result_summary={"backend_run_id": "backend_s15"},
            adapter_approval_envelope={"schema_version": "s12.adapter_envelope.v1"},
            adapter_result_envelope={"backend_run_id": "backend_s15"},
        )
    )
    artifact_path = tmp_path / "hits_raw.csv"
    artifact_path.write_text("target,uniprot_accession,hmm_score,evalue,length\n", encoding="utf-8")
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="artifact_hits",
            session_id=session.session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.RESULT,
            storage_uri=str(artifact_path),
            relative_path="aox_hmm/hits_raw.csv",
            created_at=now,
            metadata={"source_code_artifact_id": "artifact_source", "source_code_digest": "sha256:source"},
        )
    )

    evidence = _s15_build_evidence_bundle(
        repositories,
        scenario_id=S15_AOX_HMM_SCENARIO_ID,
        session_id=session.session_id,
        prompt="Run AOX/HMM",
        prerequisite_report={"status": "ok", "required": ["llm"]},
        workspace={"conversation": [{"role": "assistant", "content": "AOX/HMM mining completed."}]},
        artifacts=repositories.artifacts.list_by_session(session.session_id),
        required_paths=S15_AOX_HMM_FIXED_DELIVERABLES,
        final_output_validation={"passed": True, "errors": []},
    )
    validation = _s15_validate_evidence_bundle(evidence)

    assert validation["passed"] is True
    assert evidence["sandbox_workspace_id"] == "sbx_s15"
    assert evidence["approval_ids"] == ["approval_s15"]
    assert evidence["route_policy_ids"] == ["bio.hmmer_search.provider:v1"]
    assert evidence["toolchain_ids"] == ["ebi_hmmer_rest.refprot:v1"]
    assert evidence["provider_config_digests"] == ["sha256:provider-config"]
    assert evidence["source_snapshot_digests"] == ["sha256:source"]
    assert evidence["backend_run_ids"] == ["backend_s15"]
    assert evidence["operation_trace"][0]["expected_output_paths"] == ["aox_hmm/hits_raw.csv"]
    assert evidence["sandbox_runs"][0]["exit_code"] == 0
    assert evidence["sandbox_runs"][0]["stdout_summary"] == "registered AOX/HMM outputs"
    assert evidence["sandbox_runs"][0]["changed_files_summary"] == {
        "created": ["aox_hmm/hits_raw.csv"]
    }


def test_s15_live_product_path_rejects_legacy_execution_pipeline() -> None:
    evidence = {
        "sandbox_runs": [
            {
                "sandbox_run_id": "run_s15",
                "status": "completed",
                "source_snapshot_artifact_id": "artifact_source",
                "source_tree_digest": "sha256:source",
            }
        ],
        "approval_trace": [{"approval_id": "approval_s15", "status": "approved"}],
        "operation_trace": [
            {
                "operation_id": "op_s15",
                "status": "completed",
                "approval_id": "approval_s15",
            }
        ],
        "route_policy_ids": [
            S15_ROUTE_POLICY_IDS["bio.ncbi_fetch_proteins"],
            S15_ROUTE_POLICY_IDS["bio.uniprot_fetch"],
            S15_ROUTE_POLICY_IDS["bio.hmmer_search"],
            S15_ROUTE_POLICY_IDS["bio_tools.cdhit"],
            S15_ROUTE_POLICY_IDS["bio_tools.mafft"],
            S15_ROUTE_POLICY_IDS["bio_tools.hmmbuild"],
            S15_ROUTE_POLICY_IDS["bio_tools.hmmalign"],
        ],
    }

    accepted = _s15_validate_live_product_path(
        evidence,
        workspace={"pending_approvals": []},
        has_legacy_execution_pipeline=False,
    )
    rejected = _s15_validate_live_product_path(
        evidence,
        workspace={"pending_approvals": []},
        has_legacy_execution_pipeline=True,
    )

    assert accepted["passed"] is True
    assert rejected["passed"] is False
    assert {"error_code": "live_legacy_pipeline_forbidden"} in rejected["errors"]


def test_s15_legacy_pipeline_detector_ignores_docs_prose() -> None:
    assert (
        _s15_event_text_has_legacy_execution_pipeline(
            '{"content": "Do not use execution.pipeline.start for AOX/HMM."}'
        )
        is False
    )
    assert (
        _s15_event_text_has_legacy_execution_pipeline(
            '{"tool_name": "execution.pipeline.start", "status": "called"}'
        )
        is True
    )


def test_s15_live_readiness_uses_sandbox_records_not_legacy_execution_capability(tmp_path) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    now = "2026-05-31T00:00:00+00:00"
    session_id = "sess_s15_live_ready"
    repositories.sessions.save(
        Session(
            session_id=session_id,
            project_id="proj_001",
            title="S15 live readiness",
            objective="Validate sandbox-first readiness.",
            status=SessionStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent_executor",
            session_id=session_id,
            lane_id=None,
            task_id=None,
            name="Executor",
            role="executor",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at=now,
            updated_at=now,
            member_id="member_executor",
        )
    )
    for relative_path in sorted(S15_AOX_HMM_FIXED_DELIVERABLES):
        path = tmp_path / relative_path.replace("/", "_")
        path.write_text("placeholder\n", encoding="utf-8")
        repositories.artifacts.save(
            SessionArtifactRecord(
                artifact_id=f"artifact_{relative_path.replace('/', '_')}",
                session_id=session_id,
                task_id=None,
                lane_id=None,
                invocation_id=None,
                run_id=None,
                kind=ArtifactKind.RESULT,
                storage_uri=str(path),
                relative_path=relative_path,
                created_at=now,
                metadata={},
            )
        )
    repositories.sandbox_workspaces.save(
        SandboxWorkspaceRecord(
            sandbox_workspace_id="sbx_s15_ready",
            session_id=session_id,
            agent_member_id="member_executor",
            agent_id="agent_executor",
            status=SandboxWorkspaceStatus.READY,
            image_ref="localhost/openzyme-pipeline-sandbox:dev",
            image_digest="sha256:image",
            image_version="dev",
            sandbox_protocol_version="s09",
            image_compatibility=SandboxImageCompatibility.COMPATIBLE,
            manifest_version="1",
            created_at=now,
            last_attached_at=now,
        )
    )
    repositories.sandbox_runs.save(
        SandboxRunRecord(
            sandbox_run_id="run_s15_ready",
            session_id=session_id,
            sandbox_workspace_id="sbx_s15_ready",
            agent_id="agent_executor",
            argv=("python", "src/aox_hmm.py"),
            argv_digest="sha256:argv",
            cwd="/workspace",
            env_digest="sha256:env",
            status=SandboxRunStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            source_snapshot_artifact_id=None,
            source_tree_digest="sha256:source",
        )
    )
    workspace = {
        "pending_approvals": [],
        "task_board": {
            "items": [
                {
                    "task": {
                        "task_id": "task_aox_hmm_execution",
                        "status": "completed",
                    }
                }
            ]
        },
        "capabilities": {},
        "conversation": [{"role": "assistant", "content": "AOX/HMM complete."}],
    }

    assert _s15_live_workspace_ready(
        repositories,
        session_id=session_id,
        workspace=workspace,
    )


def test_s15_live_prerequisite_report_requires_sandbox_image(monkeypatch) -> None:
    monkeypatch.setenv("OPENZYME_NCBI_EMAIL", "dev@example.org")
    monkeypatch.setattr("openzyme_host_api.evals.live_e2e_skip_reason", lambda settings: None)
    monkeypatch.setattr("openzyme_host_api.evals.live_llm_skip_reason", lambda settings: None)
    monkeypatch.setattr("openzyme_host_api.evals.live_tavily_skip_reason", lambda settings: None)
    monkeypatch.setattr("openzyme_host_api.evals.live_hpc_skip_reason", lambda settings: None)
    monkeypatch.setattr("openzyme_host_api.evals.shutil.which", lambda binary: "/usr/bin/podman")

    def fake_run(args, **kwargs):
        del kwargs
        if args[:2] == ["podman", "info"]:
            return subprocess.CompletedProcess(args, 0, stdout="true\n", stderr="")
        if args[:3] == ["podman", "image", "exists"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="missing image")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr("openzyme_host_api.evals.subprocess.run", fake_run)
    reset_settings_cache()
    try:
        report = _s15_live_prerequisite_report()
    finally:
        reset_settings_cache()

    image_check = next(check for check in report["checks"] if check["name"] == "sandbox_image")
    missing_names = {check["name"] for check in report["missing"]}
    assert report["status"] == "prerequisite_missing"
    assert "sandbox_image" in report["required"]
    assert "sandbox_image" in missing_names
    assert image_check["status"] == "prerequisite_missing"
    assert image_check["error_code"] == "sandbox_image_missing"


def test_s15_bootstrap_live_sandbox_image_registers_probe_digest(monkeypatch) -> None:
    image_digest = "sha256:" + "b" * 64
    monkeypatch.setenv("OPENZYME_NCBI_EMAIL", "dev@example.org")
    monkeypatch.setattr("openzyme_host_api.evals.live_e2e_skip_reason", lambda settings: None)
    monkeypatch.setattr("openzyme_host_api.evals.live_llm_skip_reason", lambda settings: None)
    monkeypatch.setattr("openzyme_host_api.evals.live_tavily_skip_reason", lambda settings: None)
    monkeypatch.setattr("openzyme_host_api.evals.live_hpc_skip_reason", lambda settings: None)
    monkeypatch.setattr("openzyme_host_api.evals.shutil.which", lambda binary: "/usr/bin/podman")

    def fake_run(args, **kwargs):
        del kwargs
        if args[:2] == ["podman", "info"]:
            return subprocess.CompletedProcess(args, 0, stdout="true\n", stderr="")
        if args[:3] == ["podman", "image", "exists"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:3] == ["podman", "image", "inspect"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"{image_digest}\n", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr("openzyme_host_api.evals.subprocess.run", fake_run)
    reset_settings_cache()
    try:
        report = _s15_live_prerequisite_report()
    finally:
        reset_settings_cache()
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    _s15_bootstrap_live_sandbox_image(repositories, report)

    image = repositories.sandbox_images.get_default()
    image_check = next(check for check in report["checks"] if check["name"] == "sandbox_image")
    assert report["status"] == "ok"
    assert image_check["image_digest"] == image_digest
    assert image is not None
    assert image.image_digest == image_digest
    assert image.compatibility is SandboxImageCompatibility.COMPATIBLE_NON_CUTOVER_GRADE


def test_v3_live_eval_reports_s15_prerequisite_missing_without_fixture_fallback(monkeypatch) -> None:
    monkeypatch.setattr("openzyme_runtime.settings.load_env_files", lambda *args, **kwargs: None)
    for key in (
        "OPENZYME_TEST_ENABLE_LIVE_E2E",
        "OPENZYME_TEST_ENABLE_LIVE_LLM",
        "OPENZYME_TEST_ENABLE_LIVE_TAVILY",
        "OPENZYME_TEST_ENABLE_LIVE_HPC",
        "OPENZYME_LLM_API_KEY",
        "TAVILY_API_KEY",
        "OPENZYME_HPC_RUNNER_CONFIG",
        "HPC_RUNNER_CONFIG",
        "OPENZYME_NCBI_EMAIL",
        "NCBI_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)
    reset_settings_cache()

    try:
        summary = run_v3_s15_live_evals(upload_results=False)
    finally:
        reset_settings_cache()

    assert summary["scenario_count"] == 1
    assert summary["passed"] == 0
    assert summary["failed"] == 0
    assert summary["prerequisite_missing"] == 1
    result = summary["results"][0]
    assert result["scenario_id"] == S15_AOX_HMM_SCENARIO_ID
    assert result["scenario_class"] == "live"
    assert result["status"] == "prerequisite_missing"
    assert str(result["fixed_prompt_digest"]).startswith("sha256:")
    assert str(result["config_snapshot_digest"]).startswith("sha256:")
    assert str(result["prerequisite_report_digest"]).startswith("sha256:")
    assert result["evidence_bundle_digest"] is None
    assert result["evidence_sealed"] is False
    assert result["evidence_bundle"] is None
    assert result["checks"]["fixture_dependencies_forbidden"] is True
    assert set(result["required_artifacts"]) == S15_AOX_HMM_FIXED_DELIVERABLES
    assert result["prerequisite_report"]["status"] == "prerequisite_missing"


def test_s15_live_scenario_rejects_fixture_dependency_injection() -> None:
    with pytest.raises(ValueError, match="cannot use fixture dependencies"):
        _run_v3_aox_hmm_prompt_scenario(
            foundation_builder=build_local_eval_runtime,
            model_factory=None,
            scenario_class="live",
            use_fixture_dependencies=True,
        )
