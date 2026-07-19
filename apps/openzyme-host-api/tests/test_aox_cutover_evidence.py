from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from openzyme_core.workflow_knowledge import default_workflow_registry
from openzyme_host_api.aox_cutover_cli import main as cutover_cli_main
from openzyme_host_api.aox_cutover_launch import AoxCutoverLaunchError
from openzyme_host_api.aox_cutover_evidence import AoxCutoverCampaign
from openzyme_host_api.aox_cutover_evidence import AOX_TOOLCHAIN_RUNTIME_CONTRACTS
from openzyme_host_api.aox_cutover_evidence import AttemptRunRecord
from openzyme_host_api.aox_cutover_evidence import assert_public_safe_payload
from openzyme_host_api.aox_cutover_evidence import aox_hpc_workspace_id
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import canonical_json_bytes
from openzyme_host_api.aox_cutover_evidence import controlled_operation_digest
from openzyme_host_api.aox_cutover_evidence import create_blank_world_roots
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_cutover_evidence import evaluate_campaign
from openzyme_host_api.aox_cutover_evidence import FAULT_ARTIFACT_BYTE_FLIP_ID
from openzyme_host_api.aox_cutover_evidence import inject_artifact_byte_flip
from openzyme_host_api.aox_cutover_evidence import KNOWN_POSITIVE_PROBE_ID
from openzyme_host_api.aox_cutover_evidence import KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS
from openzyme_host_api.aox_cutover_evidence import KNOWN_POSITIVE_PROBE_SCHEMA_ID
from openzyme_host_api.aox_cutover_evidence import (
    KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS,
)
from openzyme_host_api.aox_cutover_evidence import safe_micu_ledger_snapshot
from openzyme_host_api.aox_cutover_evidence import project_formal_delegation_request
from openzyme_host_api.aox_cutover_evidence import SEALED_SOURCE_TREE_SCHEMA_ID
from openzyme_host_api.aox_cutover_evidence import seal_source_tree_envelope
from openzyme_host_api.aox_cutover_evidence import seal_campaign_decision
from openzyme_host_api.aox_cutover_evidence import seal_attempt_bundle
from openzyme_host_api.aox_cutover_evidence import VerificationResult
from openzyme_host_api.aox_cutover_evidence import typed_empty_artifact_validation_receipt
from openzyme_host_api.aox_cutover_evidence import verify_sealed_source_tree_envelope
from openzyme_host_api.aox_cutover_evidence import verify_attempt_bundle
from openzyme_host_api.aox_cutover_evidence import build_attempt_bundle
from openzyme_pipeline import aox_hmmer
from openzyme_pipeline import aox_motif
from openzyme_pipeline import aox_reference
from openzyme_pipeline import aox_sequence_join
from openzyme_pipeline import aox_similarity
from openzyme_runtime import DEFAULT_PROVIDER_LIMITS
from openzyme_runtime import LiveMicuTokenLedger


REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_ALIGNMENT = (
    REPO_ROOT
    / "packages/openzyme-pipeline/tests/fixtures/aox_motif_rule_score_v1/alignment.fasta"
)
AOX_POST_UNIPROT_FILTER_ID = aox_sequence_join.CONTRACT_ID
AOX_POST_UNIPROT_FILTER_CONTRACT_DIGEST = aox_sequence_join.CONTRACT_DIGEST
AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID = "aox_upstream_empty_materialization@1"
AOX_UPSTREAM_EMPTY_MATERIALIZATION_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID,
        "input_contract_id": aox_hmmer.CONTRACT_ID,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
        "outputs": [
            "aox_hmm/hits_len650_700_200.csv",
            "aox_hmm/target.fasta",
        ],
    }
)
AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID = "aox_reference_only_scoring_alignment@1"
AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
        "trigger": "empty_scoring_input_targets",
        "input": "aox_hmm/AOX_scoring_input.fasta",
        "output": "aox_hmm/AOX_scoring_alignment.fasta",
    }
)
AOX_EMPTY_MEMBERSHIP_ID = "canonical_empty_cluster_membership@1"
AOX_EMPTY_MEMBERSHIP_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_EMPTY_MEMBERSHIP_ID,
        "membership_schema_id": aox_similarity.MEMBERSHIP_SCHEMA_ID,
        "identity_threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
        "output": "aox_hmm/AOX_candidates_cdhit85.clusters.csv",
    }
)


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _effective_config(
    ledger_identity_digest: str | None = None,
) -> dict[str, object]:
    return {
        "schema_id": "aox_blank_world_runtime_config@1",
        "host": {
            "deployment_profile": "local-dev",
            "storage_profile": "single_process_sqlite",
            "background_runtime_enabled": False,
            "debug_enabled": False,
            "principal_count": 0,
        },
        "execution": {
            "backend": "hpc",
            "hpc_runner_config_digest": _digest("hpc-runner-config"),
            "aox_runner_contract_expectations": {
                "schema_id": "aox_runner_contract_expectations@1",
                "manifest_digest": _digest("runner-contract-manifest"),
                "contracts": {
                    contract["tool_id"]: {
                        "adapter_id": contract["adapter_id"],
                        "command_template_id": contract["command_template_id"],
                        "runner_contract_digest": _digest(
                            f"{tool_name}-runner-contract"
                        ),
                    }
                    for tool_name, contract in AOX_TOOLCHAIN_RUNTIME_CONTRACTS.items()
                },
            },
        },
        "limits": dict(DEFAULT_PROVIDER_LIMITS),
        "llm": {
            "enabled": True,
            "model": "micu-test-model",
            "base_url_endpoint": "https://www.micuapi.ai/v1",
            "extra_body_digest": _digest("llm-extra-body"),
            "default_headers_digest": _digest("llm-default-headers"),
            "use_responses_api": True,
            "max_tokens": 1_024,
            "timeout": 45.0,
            "max_retries": 3,
            "temperature": 0.0,
            "structured_output_method": "function_calling",
            "structured_output_retry_backoff_seconds": 0.5,
            "purpose_policies": {},
            "context_window_tokens": 200_000,
            "default_output_tokens": 4_000,
            "context_warn_ratio": 0.8,
            "context_auto_compact_ratio": 0.85,
            "context_emergency_ratio": 0.9,
            "tokenizer_enabled": True,
        },
        "research": {
            "max_units": 3,
            "allow_clarification": False,
            "max_research_iterations": 3,
            "max_react_tool_calls": 4,
            "max_concurrent_research_units": 2,
            "tavily_max_results": 3,
            "tavily_topic": "general",
            "tavily_timeout_seconds": 30.0,
            "mcp_enabled": True,
            "mcp_tool_allowlist": ["pubmed.search"],
            "provider_timeout_seconds": 20.0,
            "provider_max_attempts": 2,
            "credential_slots": {
                "llm": True,
                "ncbi": True,
                "semantic_scholar": False,
                "tavily": False,
            },
            "ncbi_identity_digest": _digest("ncbi-identity"),
        },
        "tracing": {
            "enabled": False,
            "project_name_digest": _digest("tracing-project"),
        },
        "test_opt_in": {
            "live_llm": True,
            "live_tavily": False,
            "live_hpc": True,
            "live_e2e": True,
            "quality_eval": False,
            "upload_langsmith": False,
        },
        "driver": {
            "scenario": "aox_blank_world_cutover",
            "approval_mode": "auto",
            "browser_observation_mode": "chrome_devtools_mcp_file_handoff",
            "timeout_seconds": 7_200.0,
            "max_drains": 120,
            "max_signals_per_drain": 10,
            "max_steps_per_agent": 16,
            "browser_poll_interval_seconds": 0.5,
            "browser_approval_timeout_seconds": 300.0,
            "browser_completion_hold_seconds": 60.0,
            "browser_observation_submission_timeout_seconds": 180.0,
            "ui_dist_digest": None,
            "micu_hard_limit_tokens": 500_000_000,
            "micu_ledger_identity_digest": (
                ledger_identity_digest or _digest("persistent-ledger")
            ),
        },
    }


def _identity(
    ledger_identity_digest: str | None = None,
) -> dict[str, str]:
    workflow = next(
        manifest
        for manifest in default_workflow_registry().list_manifests()
        if manifest.workflow_id == "aox-hmm-live"
    )
    return {
        "git_commit": "a" * 40,
        "config_digest": canonical_digest(_effective_config(ledger_identity_digest)),
        "workflow_ref": workflow.selection_ref,
        "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
        "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
        "image_digest": _digest("image"),
        "sdk_digest": _digest("sdk"),
    }


def _delegation_workflow_receipt(
    *,
    task_id: str,
    role: str,
) -> dict[str, object]:
    workflow = next(
        manifest
        for manifest in default_workflow_registry().list_manifests()
        if manifest.workflow_id == "aox-hmm-live"
    )
    workflow_refs = [workflow.selection_ref] if role == "executor" else []
    workflow_manifests = [workflow.to_dict()] if role == "executor" else []
    agent_id = f"agent_{role}"
    display_name = role.capitalize()
    payload = {
        "task_id": task_id,
        "instructions": f"Complete the canonical {role} task.",
        "role": role,
        "agent_id": agent_id,
        "nickname": role,
        "display_name": display_name,
        "handle": f"@{role}",
        "workflow_refs": workflow_refs,
        "workflow_manifests": workflow_manifests,
    }
    document_id = f"doc_delegate_{task_id}"
    projection = project_formal_delegation_request(
        payload,
        document_id=document_id,
    )
    return {
        "assigned_ref": agent_id,
        "delegation_request_ref": document_id,
        "delegation_request_digest": canonical_digest(projection),
        "delegation_request": projection,
        "workflow_refs": workflow_refs,
        "workflow_manifests": workflow_manifests,
    }


def _allowed_prerequisites(
    identity: dict[str, str] | None = None,
) -> dict[str, object]:
    pinned = identity or _identity()
    hmmer_digest = _digest("hmmer-sif")
    image_digests = {
        contract["toolchain_id"]: (
            hmmer_digest
            if tool_name in {"hmmbuild", "hmmalign"}
            else _digest(f"{tool_name}-sif")
        )
        for tool_name, contract in AOX_TOOLCHAIN_RUNTIME_CONTRACTS.items()
    }
    return {
        "git_commit": pinned["git_commit"],
        "config_digest": pinned["config_digest"],
        "workflow_ref": pinned["workflow_ref"],
        "image_digest": pinned["image_digest"],
        "sdk_digest": pinned["sdk_digest"],
        "toolchain_image_digests": image_digests,
        "credential_slots": {
            "llm": True,
            "ncbi": True,
            "semantic_scholar": False,
            "tavily": False,
        },
        "ncbi_identity": _digest("ncbi-identity"),
        "prompt_accessions": {
            "formal_ncbi": list(aox_reference.NCBI_REFERENCE_ACCESSIONS),
            "probe_ncbi": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
            "probe_uniprot": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
        },
    }


def _toolchain_identity_fields(tool_name: str) -> dict[str, str]:
    contract = AOX_TOOLCHAIN_RUNTIME_CONTRACTS[tool_name]
    image_digest = dict(_allowed_prerequisites()["toolchain_image_digests"])[
        contract["toolchain_id"]
    ]
    return {
        "toolchain_id": contract["toolchain_id"],
        "runtime_identity_schema": "mcp_hpc_toolchain_runtime_identity@1",
        "attestation_scope": "same_ssh_login_shell_pre_exec",
        "execution_mode": "ssh",
        "tool_id": contract["tool_id"],
        "adapter_id": contract["adapter_id"],
        "command_template_id": contract["command_template_id"],
        "runner_contract_digest": _digest(f"{tool_name}-runner-contract"),
        "image_digest": image_digest,
    }


def _public_api_receipts(
    session_id: str = "sess_aox_live",
) -> list[dict[str, object]]:
    create_request = {
        "session_id": session_id,
        "project_id": "aox-blank-world-cutover",
        "objective": (
            "Run the canonical blank-world AOX/HMM product path and publish "
            "a source-linked scientific report."
        ),
        "title": "AOX blank-world formal",
    }
    message_request = {
        "message_digest": _digest("entry-message"),
        "skill_keys": [_identity()["workflow_ref"]],
    }
    drain_request = {
        "max_signals": 10,
        "max_steps_per_agent": 16,
        "auto_enqueue_ready_tasks": False,
    }
    return [
        {
            "sequence": 1,
            "method": "POST",
            "route": "/v3/sessions",
            "status_code": 201,
            "request_digest": canonical_digest(create_request),
            "response_digest": _digest("create-session-response"),
            "response_semantic_digest": _digest("create-session-semantic"),
        },
        {
            "sequence": 2,
            "method": "POST",
            "route": f"/v3/sessions/{session_id}/messages",
            "status_code": 202,
            "request_digest": canonical_digest(message_request),
            "response_digest": _digest("entry-message-response"),
            "response_semantic_digest": _digest("entry-message-semantic"),
        },
        {
            "sequence": 3,
            "method": "GET",
            "route": f"/v3/sessions/{session_id}/events?replay=1&after_cursor=0",
            "status_code": 200,
            "request_digest": canonical_digest({"replay": True, "after_cursor": 0}),
            "response_digest": _digest("events-pre-response"),
            "response_semantic_digest": _digest("events-pre-semantic"),
        },
        {
            "sequence": 4,
            "method": "POST",
            "route": f"/v3/sessions/{session_id}/runtime/drain",
            "status_code": 200,
            "request_digest": canonical_digest(drain_request),
            "response_digest": _digest("drain-response"),
            "response_semantic_digest": _digest("drain-semantic"),
        },
        {
            "sequence": 5,
            "method": "GET",
            "route": f"/v3/sessions/{session_id}/workspace",
            "status_code": 200,
            "request_digest": canonical_digest({}),
            "response_digest": _digest("public-final-workspace-response"),
            "response_semantic_digest": _digest("public-final-workspace"),
        },
        {
            "sequence": 6,
            "method": "GET",
            "route": f"/v3/sessions/{session_id}/events?replay=1&after_cursor=0",
            "status_code": 200,
            "request_digest": canonical_digest({"replay": True, "after_cursor": 0}),
            "response_digest": _digest("public-final-events-response"),
            "response_semantic_digest": _digest("public-final-events"),
        },
    ]


def _ledger_snapshot(
    *,
    charged_tokens: int = 10,
    attempt_count: int = 1,
) -> dict[str, object]:
    input_tokens = charged_tokens // 2
    output_tokens = charged_tokens - input_tokens
    grouped_counters = {
        "attempt_count": attempt_count,
        "charged_tokens": charged_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "actual_input_tokens": input_tokens,
        "actual_output_tokens": output_tokens,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "estimated_attempt_count": 0,
        "reservation_overage_tokens": 0,
        "hard_limit_breach_count": 0,
    }
    return {
        "ledger_identity_digest": _digest("persistent-ledger"),
        "hard_limit_tokens": 500_000_000,
        "charged_tokens": charged_tokens,
        "remaining_tokens": 500_000_000 - charged_tokens,
        "hard_limit_overage_tokens": 0,
        "attempt_count": attempt_count,
        "estimated_attempt_count": 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "actual_input_tokens": input_tokens,
        "actual_output_tokens": output_tokens,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "reservation_overage_tokens": 0,
        "hard_limit_breach_count": 0,
        "by_scenario": [{"scenario": "aox_blank_world_cutover", **grouped_counters}],
        "by_model": [{"model": "micu-live", **grouped_counters}],
    }


def _write_artifact(root: Path, relative_path: str, content: bytes) -> str:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _source_tree_digest(files: dict[str, bytes]) -> str:
    entries = [
        {
            "relative_path": relative_path,
            "content_digest": _digest_bytes(content),
            "size_bytes": len(content),
        }
        for relative_path, content in sorted(files.items())
    ]
    return _digest_bytes(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def test_sealed_source_tree_envelope_round_trips_sorted_files(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    files = {
        "z.py": b"Z = 1\n",
        "openzyme_pipeline/a.py": b"A = 1\n",
        "openzyme_pipeline/enz\N{LATIN SMALL LETTER Y WITH DIAERESIS}me.py": b"ACTIVITY = 1\n",
    }
    for relative_path, content in files.items():
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    expected_digest = _source_tree_digest(files)

    sealed = seal_source_tree_envelope(
        source_root,
        expected_source_tree_digest=expected_digest,
    )
    decoded = verify_sealed_source_tree_envelope(
        sealed,
        expected_source_tree_digest=expected_digest,
    )

    assert decoded["schema_id"] == SEALED_SOURCE_TREE_SCHEMA_ID
    assert decoded["source_tree_digest"] == expected_digest
    assert [item["relative_path"] for item in decoded["files"]] == sorted(files)
    assert sealed == canonical_json_bytes(decoded) + b"\n"


def test_sealed_source_tree_encoder_rejects_empty_symlink_and_nonregular_entries(
    tmp_path: Path,
) -> None:
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    with pytest.raises(CutoverEvidenceError) as empty_error:
        seal_source_tree_envelope(
            empty_root,
            expected_source_tree_digest=_digest("empty"),
        )
    assert empty_error.value.code == "sealed_source_tree_empty"

    symlink_root = tmp_path / "symlink"
    symlink_root.mkdir()
    target = tmp_path / "target.py"
    target.write_text("unsafe = True\n", encoding="utf-8")
    (symlink_root / "linked.py").symlink_to(target)
    with pytest.raises(CutoverEvidenceError) as symlink_error:
        seal_source_tree_envelope(
            symlink_root,
            expected_source_tree_digest=_digest("symlink"),
        )
    assert symlink_error.value.code == "sealed_source_tree_entry_invalid"

    fifo_root = tmp_path / "fifo"
    fifo_root.mkdir()
    os.mkfifo(fifo_root / "named-pipe")
    with pytest.raises(CutoverEvidenceError) as fifo_error:
        seal_source_tree_envelope(
            fifo_root,
            expected_source_tree_digest=_digest("fifo"),
        )
    assert fifo_error.value.code == "sealed_source_tree_entry_invalid"


def test_sealed_source_tree_decoder_rejects_unsafe_path_and_file_tamper(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "main.py").write_bytes(b"print('safe')\n")
    expected_digest = _source_tree_digest({"main.py": b"print('safe')\n"})
    sealed = seal_source_tree_envelope(
        source_root,
        expected_source_tree_digest=expected_digest,
    )
    envelope = json.loads(sealed)

    unsafe = json.loads(sealed)
    unsafe["files"][0]["relative_path"] = "../main.py"
    with pytest.raises(CutoverEvidenceError) as unsafe_error:
        verify_sealed_source_tree_envelope(
            canonical_json_bytes(unsafe) + b"\n",
            expected_source_tree_digest=expected_digest,
        )
    assert unsafe_error.value.code == "sealed_source_tree_path_invalid"

    envelope["files"][0]["content_base64"] = base64.b64encode(
        b"print('tampered')\n"
    ).decode("ascii")
    with pytest.raises(CutoverEvidenceError) as tamper_error:
        verify_sealed_source_tree_envelope(
            canonical_json_bytes(envelope) + b"\n",
            expected_source_tree_digest=expected_digest,
        )
    assert tamper_error.value.code == "sealed_source_tree_file_digest_mismatch"


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        (b"SOURCE = '/home/operator/private.py'\n", "public_projection_host_path"),
        (
            b"api_key = 'sk-examplecredential123456'\n",
            "public_projection_secret_value",
        ),
    ],
)
def test_sealed_source_tree_rejects_private_decoded_source(
    tmp_path: Path,
    content: bytes,
    expected_code: str,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "main.py").write_bytes(content)

    with pytest.raises(CutoverEvidenceError) as error:
        seal_source_tree_envelope(
            source_root,
            expected_source_tree_digest=_source_tree_digest({"main.py": content}),
        )

    assert error.value.code == expected_code
    assert content.decode("utf-8").strip() not in str(error.value)


def test_sealed_source_tree_allows_closed_aox_suffixes_and_python_path_join(
    tmp_path: Path,
) -> None:
    content = (
        "from pathlib import Path\n"
        "outputs = [\n"
        "    '/provider_parsed/proteins.fasta',\n"
        "    '/provider_parsed/parsed_hits.csv',\n"
        "    '/provider_parsed/sequences.fasta',\n"
        "    '/provider_parsed/metadata.json',\n"
        "]\n"
        "copied = [Path('aox_hmm')/p.name for p in []]\n"
    ).encode("utf-8")
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "main.py").write_bytes(content)
    expected_digest = _source_tree_digest({"main.py": content})

    sealed = seal_source_tree_envelope(
        source_root,
        expected_source_tree_digest=expected_digest,
    )
    decoded = verify_sealed_source_tree_envelope(
        sealed,
        expected_source_tree_digest=expected_digest,
    )

    assert decoded["source_tree_digest"] == expected_digest


def _refresh_operation_identity(
    operation: dict[str, object],
    *,
    hpc_workspace_label: str | None = None,
) -> None:
    operation["canonical_ref_kind"] = "controlled_operation"
    route_policy_id = str(operation.get("route_policy_id") or "pending.route:v1")
    route_name = route_policy_id.partition(":")[0]
    route_parts = route_name.split(".")
    if len(route_parts) >= 3 and route_parts[-1] in {"hpc", "provider"}:
        sdk_module = ".".join(route_parts[:-2])
        function_name = route_parts[-2]
    elif "." in route_name:
        sdk_module, function_name = route_name.rsplit(".", 1)
    else:
        sdk_module, function_name = "openzyme_pipeline", route_name
    inputs = [dict(item) for item in operation.get("inputs") or []]
    outputs = [dict(item) for item in operation.get("outputs") or []]
    selected_backend = str(operation.get("selected_backend") or "sandbox_sdk")
    source_snapshot_digest = str(
        operation.get("source_snapshot_digest") or _digest("aox-pipeline-source")
    )
    sandbox_workspace_id = str(
        operation.get("sandbox_workspace_id") or "sandbox_workspace_aox"
    )
    if selected_backend == "hpc" and hpc_workspace_label is not None:
        operation["hpc_workspace_id"] = aox_hpc_workspace_id(
            sandbox_workspace_id=sandbox_workspace_id,
            hpc_workspace_label=hpc_workspace_label,
        )
    params_digest = canonical_digest(dict(operation.get("parameters") or {}))
    operation["params_digest"] = params_digest
    material = {
        "schema_version": "s12.adapter_envelope.v1",
        "sandbox_workspace_id": sandbox_workspace_id,
        "source_snapshot_digest": source_snapshot_digest,
        "sdk_module": sdk_module,
        "function_name": function_name,
        "params_digest": params_digest,
        "input_artifact_ids": [str(item.get("artifact_id") or "") for item in inputs],
        "input_artifact_digests": [
            str(item.get("content_digest") or "") for item in inputs
        ],
        "placement": "trusted_host_supervised",
        "hpc_workspace_id": (
            str(operation.get("hpc_workspace_id") or "hpc_workspace_aox")
            if selected_backend == "hpc"
            else None
        ),
        "stage_refs": [],
        "selected_backend": selected_backend,
        "route_reason": str(
            operation.get("route_reason") or "workflow_selected_controlled_route"
        ),
        "route_policy_id": route_policy_id,
        "runtime_packaging_id": "openzyme_pipeline_sdk@1",
        "toolchain_id": (
            AOX_TOOLCHAIN_RUNTIME_CONTRACTS.get(
                "cd-hit" if function_name == "cdhit" else function_name,
                {"toolchain_id": f"{function_name}@test"},
            )["toolchain_id"]
            if selected_backend == "hpc"
            else None
        ),
        "provider_config_digest": _digest("provider-config"),
        "resource_class": "network" if selected_backend == "provider_http" else "cpu",
        "resource_estimate": {},
        "expected_outputs": {
            "items": [
                {"artifact_id": str(item.get("artifact_id") or "")} for item in outputs
            ]
        },
        "planned_fetch_intent": {},
        "approval_requirement": {"required": True},
    }
    operation["operation_identity_schema"] = "openzyme_controlled_operation_s12@1"
    operation["operation_identity_material"] = material
    operation["operation_identity_digest"] = controlled_operation_digest(material)


def _refresh_sandbox_calculation_identity(operation: dict[str, object]) -> None:
    inputs = [dict(item) for item in operation.get("inputs") or []]
    outputs = [dict(item) for item in operation.get("outputs") or []]
    params_digest = canonical_digest(dict(operation.get("parameters") or {}))
    calculation_id = str(operation.get("kind") or operation["operation_id"])
    source_snapshot_digest = _digest("aox-pipeline-source")
    operation.update(
        {
            "canonical_ref_kind": "sandbox_calculation",
            "route_policy_id": "sandbox.calculation:v1",
            "selected_backend": "sandbox_run",
            "backend_run_id": "sandbox_run_aox",
            "source_snapshot_digest": source_snapshot_digest,
            "params_digest": params_digest,
        }
    )
    calculation_contract_digest = _digest(f"contract:{calculation_id}")
    calculation_implementation_digest = _digest(f"implementation:{calculation_id}")
    if calculation_id == aox_hmmer.CONTRACT_ID:
        calculation_contract_digest = aox_hmmer.CONTRACT_DIGEST
        calculation_implementation_digest = aox_hmmer.IMPLEMENTATION_DIGEST
    elif calculation_id == AOX_POST_UNIPROT_FILTER_ID:
        calculation_contract_digest = AOX_POST_UNIPROT_FILTER_CONTRACT_DIGEST
        calculation_implementation_digest = aox_sequence_join.IMPLEMENTATION_DIGEST
    elif calculation_id == aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID:
        calculation_contract_digest = (
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        )
        calculation_implementation_digest = (
            aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        )
    elif calculation_id == aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID:
        calculation_contract_digest = (
            aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
        )
        calculation_implementation_digest = (
            aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
        )
    elif calculation_id == aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID:
        calculation_contract_digest = (
            aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
        )
        calculation_implementation_digest = (
            aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
        )
    elif calculation_id == AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID:
        calculation_contract_digest = AOX_UPSTREAM_EMPTY_MATERIALIZATION_CONTRACT_DIGEST
    elif calculation_id == AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID:
        calculation_contract_digest = (
            AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_CONTRACT_DIGEST
        )
    elif calculation_id == AOX_EMPTY_MEMBERSHIP_ID:
        calculation_contract_digest = AOX_EMPTY_MEMBERSHIP_CONTRACT_DIGEST
    material = {
        "schema_version": "openzyme_sandbox_calculation_receipt@1",
        "sandbox_run_id": "sandbox_run_aox",
        "sandbox_workspace_id": "sandbox_workspace_aox",
        "source_snapshot_artifact_id": "art_source_snapshot",
        "source_snapshot_digest": source_snapshot_digest,
        "calculation_id": calculation_id,
        "calculation_contract_digest": calculation_contract_digest,
        "calculation_implementation_digest": calculation_implementation_digest,
        "params_digest": params_digest,
        "input_artifact_ids": [str(item["artifact_id"]) for item in inputs],
        "input_artifact_digests": [str(item["content_digest"]) for item in inputs],
        "output_artifact_ids": [str(item["artifact_id"]) for item in outputs],
        "output_artifact_digests": [str(item["content_digest"]) for item in outputs],
    }
    operation["operation_identity_schema"] = "openzyme_sandbox_calculation_receipt@1"
    operation["operation_identity_material"] = material
    operation["operation_identity_digest"] = canonical_digest(material)


def _operation(
    operation_id: str,
    *,
    inputs: list[tuple[str, str]] | None = None,
    outputs: list[tuple[str, str]] | None = None,
    status: str = "completed",
    failure_code: str | None = None,
    scope: str = "formal",
) -> dict[str, object]:
    operation: dict[str, object] = {
        "operation_id": operation_id,
        "session_id": "sess_aox_live",
        "sandbox_run_id": "sandbox_run_aox",
        "sandbox_workspace_id": "sandbox_workspace_aox",
        "kind": operation_id.removeprefix("op_"),
        "scope": scope,
        "status": status,
        "terminal": True,
        "inputs": [
            {"artifact_id": artifact_id, "content_digest": digest}
            for artifact_id, digest in inputs or []
        ],
        "outputs": [
            {"artifact_id": artifact_id, "content_digest": digest}
            for artifact_id, digest in outputs or []
        ],
        "parameters": {},
    }
    if failure_code is not None:
        operation["failure_code"] = failure_code
    _refresh_operation_identity(operation)
    return operation


def _refresh_fixture_operation_identities(evidence: dict[str, object]) -> None:
    refreshed_identities: dict[str, str] = {}
    for operation in evidence["operations"]:
        if operation.get("canonical_ref_kind") == "sandbox_calculation":
            _refresh_sandbox_calculation_identity(operation)
        else:
            _refresh_operation_identity(operation)
        refreshed_identities[operation["operation_id"]] = operation[
            "operation_identity_digest"
        ]
    for approval in evidence["approvals"]:
        approval["operation_identity_digest"] = refreshed_identities[
            approval["operation_id"]
        ]


def _replace_artifact_bytes(
    artifact_root: Path,
    evidence: dict[str, object],
    *,
    artifact_id: str,
    content: bytes,
) -> str:
    artifact = next(
        item for item in evidence["artifacts"] if item["artifact_id"] == artifact_id
    )
    digest = _write_artifact(
        artifact_root,
        str(artifact["relative_path"]),
        content,
    )
    for operation in evidence["operations"]:
        for direction in ("inputs", "outputs"):
            for ref in operation.get(direction) or []:
                if ref.get("artifact_id") == artifact_id:
                    ref["content_digest"] = digest
    return digest


def _attach_typed_empty_validation(
    evidence: dict[str, object],
    *,
    artifact_id: str,
    reason: str,
    derivation_contract_id: str,
) -> None:
    artifact = next(
        item for item in evidence["artifacts"] if item["artifact_id"] == artifact_id
    )
    validation = {
        "status": "passed",
        "format": "fasta",
        "required_columns": [],
        "validation_profile": "fasta_zero_records@1",
        "empty_result_reason": reason,
        "derivation_contract_id": derivation_contract_id,
    }
    artifact["registration_validation"] = typed_empty_artifact_validation_receipt(
        kind="sequence",
        metadata={
            "format": "fasta",
            "validation_profile": "fasta_zero_records@1",
            "empty_result_reason": reason,
            "derivation_contract_id": derivation_contract_id,
            "validation": validation,
        },
    )


def _reference_only_alignment() -> bytes:
    alignment = aox_motif.score_aligned_fasta(GOLDEN_ALIGNMENT.read_bytes()).alignment
    reference = next(
        record
        for record in alignment.records
        if record.sequence_id == aox_motif.REFERENCE_ACCESSION
    )
    return f">{reference.sequence_id}\n{reference.sequence}\n".encode("ascii")


def _ncbi_reference_set() -> bytes:
    reference_sequence = _reference_only_alignment().splitlines()[1].decode("ascii")
    records: list[str] = []
    for accession in aox_reference.NCBI_REFERENCE_ACCESSIONS:
        source_id = "pdb|9AVH|A" if accession == "9AVH_A" else accession
        records.append(f">{source_id}\n{reference_sequence}\n")
    return "".join(records).encode("ascii")


def _provider_raw_envelope(
    *,
    provider: str,
    operation: str,
    body: bytes,
) -> tuple[bytes, str]:
    body_digest = _digest_bytes(body)
    envelope = (
        json.dumps(
            {
                "schema_id": "provider_raw_http_response_set@1",
                "provider": provider,
                "operation": operation,
                "responses": [
                    {
                        "ordinal": 1,
                        "phase": "response",
                        "status_code": 200,
                        "headers": {},
                        "body_encoding": "base64",
                        "body_base64": base64.b64encode(body).decode("ascii"),
                        "body_digest": body_digest,
                        "size_bytes": len(body),
                    }
                ],
            },
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )
    return envelope, body_digest


def _known_positive_probe_fixture(
    artifact_root: Path,
    *,
    hpc_workspace_label: str,
) -> dict[str, object]:
    beta_globin = (
        "MVHLTPEEKSAVTALWGKVNVDEVGGEALGRLLVVYPWTQRFFESFGDLSTPDAVMGNPKV"
        "KAHGKKVLGAFSDGLAHLDNLKGTFATLSELHCDKLHVDPENFRLLGNVLVCVLAHHFGK"
        "EFTPPVQAAYQKVVAGVANALAHKYH"
    )
    alpha_globin = (
        "MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHFDLSHGSAQVKGHG"
        "KKVADALTNAVAHVDDMPNALSALSDLHAHKLRVDPVNFKLLSHCLLVTLAAHLPAEFTP"
        "AVHASLDKFLASVSTVLTSKYR"
    )
    ncbi_fasta = (
        f">{KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS[0]}\n{beta_globin}\n"
        f">{KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS[1]}\n{alpha_globin}\n"
    ).encode("ascii")
    uniprot_fasta = (
        f">{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[0]}\n{beta_globin}\n"
        f">{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[1]}\n{alpha_globin}\n"
    ).encode("ascii")
    ncbi_raw, ncbi_response_digest = _provider_raw_envelope(
        provider="ncbi",
        operation="bio.ncbi_fetch_proteins",
        body=ncbi_fasta,
    )
    uniprot_body = (
        canonical_json_bytes(
            {
                "results": [
                    {
                        "primaryAccession": accession,
                        "sequence": {"value": sequence},
                    }
                    for accession, sequence in zip(
                        KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS,
                        (beta_globin, alpha_globin),
                        strict=True,
                    )
                ]
            }
        )
        + b"\n"
    )
    uniprot_raw, uniprot_response_digest = _provider_raw_envelope(
        provider="uniprot",
        operation="bio.uniprot_fetch",
        body=uniprot_body,
    )
    mafft_alignment = ncbi_fasta
    hmm_model = b"HMMER3/f [globin-known-positive]\nNAME globin_probe\n//\n"
    clustered_fasta = uniprot_fasta
    membership = (
        "cluster_id,member_id,representative_id,is_representative,"
        "identity_to_representative,member_length\n"
        f"cluster_0,{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[0]},"
        f"{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[0]},true,1.000000,"
        f"{len(beta_globin)}\n"
        f"cluster_1,{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[1]},"
        f"{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[1]},true,1.000000,"
        f"{len(alpha_globin)}\n"
    ).encode("ascii")
    hmmalign_alignment = uniprot_fasta
    source_file_content = b"# known-positive probe source snapshot\n"
    source_file_digest = _digest_bytes(source_file_content)
    source_snapshot_digest = canonical_digest(
        [
            {
                "relative_path": "openzyme_pipeline/probe.py",
                "content_digest": source_file_digest,
                "size_bytes": len(source_file_content),
            }
        ]
    )
    source_snapshot = (
        canonical_json_bytes(
            {
                "schema_id": SEALED_SOURCE_TREE_SCHEMA_ID,
                "source_tree_digest": source_snapshot_digest,
                "files": [
                    {
                        "relative_path": "openzyme_pipeline/probe.py",
                        "size_bytes": len(source_file_content),
                        "content_digest": source_file_digest,
                        "content_base64": base64.b64encode(
                            source_file_content
                        ).decode("ascii"),
                    }
                ],
            }
        )
        + b"\n"
    )

    contents = {
        "art_probe_source_snapshot": (
            "probe/source/openzyme-pipeline-snapshot.json",
            source_snapshot,
        ),
        "art_probe_ncbi_raw": ("probe/provider/ncbi-raw.json", ncbi_raw),
        "art_probe_ncbi_fasta": ("probe/provider/ncbi-globins.fasta", ncbi_fasta),
        "art_probe_mafft_alignment": (
            "probe/toolchain/ncbi-globins-aligned.fasta",
            mafft_alignment,
        ),
        "art_probe_hmm_model": ("probe/toolchain/globin.hmm", hmm_model),
        "art_probe_uniprot_raw": ("probe/provider/uniprot-raw.json", uniprot_raw),
        "art_probe_uniprot_fasta": (
            "probe/provider/uniprot-globins.fasta",
            uniprot_fasta,
        ),
        "art_probe_cdhit_fasta": (
            "probe/toolchain/uniprot-globins-clustered.fasta",
            clustered_fasta,
        ),
        "art_probe_cdhit_membership": (
            "probe/toolchain/uniprot-globins-clusters.csv",
            membership,
        ),
        "art_probe_hmmalign_alignment": (
            "probe/toolchain/uniprot-globins-aligned.fasta",
            hmmalign_alignment,
        ),
    }
    digests = {
        artifact_id: _write_artifact(artifact_root, relative_path, content)
        for artifact_id, (relative_path, content) in contents.items()
    }
    session_id = "sess_probe_globin"
    task_id = "task_probe_globin"
    sandbox_run_id = "sandbox_run_probe_globin"
    sandbox_workspace_id = "sandbox_workspace_probe_globin"
    hpc_workspace_id = aox_hpc_workspace_id(
        sandbox_workspace_id=sandbox_workspace_id,
        hpc_workspace_label=hpc_workspace_label,
    )
    source_snapshot_artifact_digest = digests["art_probe_source_snapshot"]
    provenance = {
        "art_probe_source_snapshot": {
            "producer": "sandbox_source_snapshot",
            "sandbox_run_id": sandbox_run_id,
            "source_snapshot_digest": source_snapshot_digest,
        },
        "art_probe_ncbi_raw": {
            "provider": "ncbi",
            "provider_artifact_kind": "provider_raw",
        },
        "art_probe_ncbi_fasta": {
            "provider": "ncbi",
            "provider_artifact_kind": "provider_parsed",
        },
        "art_probe_mafft_alignment": {"tool": "mafft"},
        "art_probe_hmm_model": {"tool": "hmmbuild"},
        "art_probe_uniprot_raw": {
            "provider": "uniprot",
            "provider_artifact_kind": "provider_raw",
        },
        "art_probe_uniprot_fasta": {
            "provider": "uniprot",
            "provider_artifact_kind": "provider_parsed",
        },
        "art_probe_cdhit_fasta": {"tool": "cd-hit"},
        "art_probe_cdhit_membership": {"tool": "cd-hit"},
        "art_probe_hmmalign_alignment": {"tool": "hmmalign"},
    }
    artifact_kind = {
        "art_probe_source_snapshot": "code",
        "art_probe_ncbi_raw": "provider_evidence",
        "art_probe_ncbi_fasta": "sequence",
        "art_probe_mafft_alignment": "sequence",
        "art_probe_hmm_model": "model",
        "art_probe_uniprot_raw": "provider_evidence",
        "art_probe_uniprot_fasta": "sequence",
        "art_probe_cdhit_fasta": "sequence",
        "art_probe_cdhit_membership": "result",
        "art_probe_hmmalign_alignment": "sequence",
    }
    artifacts = [
        {
            "artifact_id": artifact_id,
            "relative_path": relative_path,
            "scope": "probe",
            "origin": (
                "sandbox_run"
                if artifact_id == "art_probe_source_snapshot"
                else "operation"
            ),
            "kind": artifact_kind[artifact_id],
            "provenance": {
                "probe_id": KNOWN_POSITIVE_PROBE_ID,
                **provenance[artifact_id],
            },
        }
        for artifact_id, (relative_path, _) in contents.items()
    ]

    def probe_operation(
        operation_id: str,
        *,
        inputs: list[tuple[str, str]] | None = None,
        outputs: list[tuple[str, str]],
        parameters: dict[str, object] | None = None,
        route_policy_id: str,
        selected_backend: str,
        backend_run_id: str,
    ) -> dict[str, object]:
        operation = _operation(
            operation_id,
            inputs=inputs,
            outputs=outputs,
            scope="probe",
        )
        operation.update(
            {
                "session_id": session_id,
                "task_id": task_id,
                "sandbox_run_id": sandbox_run_id,
                "sandbox_workspace_id": sandbox_workspace_id,
                "source_snapshot_artifact_id": "art_probe_source_snapshot",
                "source_snapshot_digest": source_snapshot_digest,
                "hpc_workspace_id": (
                    hpc_workspace_id if selected_backend == "hpc" else None
                ),
                "parameters": dict(parameters or {}),
                "route_policy_id": route_policy_id,
                "selected_backend": selected_backend,
                "backend_run_id": backend_run_id,
            }
        )
        _refresh_operation_identity(
            operation,
            hpc_workspace_label=hpc_workspace_label,
        )
        return operation

    operations = [
        probe_operation(
            "op_probe_ncbi",
            outputs=[
                ("art_probe_ncbi_raw", digests["art_probe_ncbi_raw"]),
                ("art_probe_ncbi_fasta", digests["art_probe_ncbi_fasta"]),
            ],
            parameters={"accessions": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS)},
            route_policy_id="bio.ncbi_fetch_proteins.provider:v1",
            selected_backend="provider_http",
            backend_run_id="invocation_probe_ncbi",
        ),
        probe_operation(
            "op_probe_mafft",
            inputs=[("art_probe_ncbi_fasta", digests["art_probe_ncbi_fasta"])],
            outputs=[
                (
                    "art_probe_mafft_alignment",
                    digests["art_probe_mafft_alignment"],
                )
            ],
            route_policy_id="bio_tools.mafft.hpc:v1",
            selected_backend="hpc",
            backend_run_id="job_probe_mafft",
        ),
        probe_operation(
            "op_probe_hmmbuild",
            inputs=[
                (
                    "art_probe_mafft_alignment",
                    digests["art_probe_mafft_alignment"],
                )
            ],
            outputs=[("art_probe_hmm_model", digests["art_probe_hmm_model"])],
            route_policy_id="bio_tools.hmmbuild.hpc:v1",
            selected_backend="hpc",
            backend_run_id="job_probe_hmmbuild",
        ),
        probe_operation(
            "op_probe_uniprot",
            outputs=[
                ("art_probe_uniprot_raw", digests["art_probe_uniprot_raw"]),
                ("art_probe_uniprot_fasta", digests["art_probe_uniprot_fasta"]),
            ],
            parameters={"accessions": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS)},
            route_policy_id="bio.uniprot_fetch.provider:v1",
            selected_backend="provider_http",
            backend_run_id="invocation_probe_uniprot",
        ),
        probe_operation(
            "op_probe_cdhit",
            inputs=[("art_probe_uniprot_fasta", digests["art_probe_uniprot_fasta"])],
            outputs=[
                ("art_probe_cdhit_fasta", digests["art_probe_cdhit_fasta"]),
                (
                    "art_probe_cdhit_membership",
                    digests["art_probe_cdhit_membership"],
                ),
            ],
            parameters={"identity": 1.0, "mode": "protein"},
            route_policy_id="bio_tools.cdhit.hpc:v1",
            selected_backend="hpc",
            backend_run_id="job_probe_cdhit",
        ),
        probe_operation(
            "op_probe_hmmalign",
            inputs=[
                ("art_probe_hmm_model", digests["art_probe_hmm_model"]),
                ("art_probe_cdhit_fasta", digests["art_probe_cdhit_fasta"]),
            ],
            outputs=[
                (
                    "art_probe_hmmalign_alignment",
                    digests["art_probe_hmmalign_alignment"],
                )
            ],
            route_policy_id="bio_tools.hmmalign.hpc:v1",
            selected_backend="hpc",
            backend_run_id="job_probe_hmmalign",
        ),
    ]
    operation_by_id = {operation["operation_id"]: operation for operation in operations}
    provider_receipts = [
        {
            "provider_record_id": "provider_record_probe_ncbi",
            "provider": "ncbi",
            "status": "completed",
            "invocation_id": "invocation_probe_ncbi",
            "operation_id": "op_probe_ncbi",
            "cache_hit": False,
            "request_digest": operation_by_id["op_probe_ncbi"]["params_digest"],
            "response_digest": ncbi_response_digest,
            "artifact_ids": ["art_probe_ncbi_raw", "art_probe_ncbi_fasta"],
            "raw_response_artifact_id": "art_probe_ncbi_raw",
            "parsed_fasta_artifact_id": "art_probe_ncbi_fasta",
        },
        {
            "provider_record_id": "provider_record_probe_uniprot",
            "provider": "uniprot",
            "status": "completed",
            "invocation_id": "invocation_probe_uniprot",
            "operation_id": "op_probe_uniprot",
            "cache_hit": False,
            "request_digest": operation_by_id["op_probe_uniprot"]["params_digest"],
            "response_digest": uniprot_response_digest,
            "artifact_ids": ["art_probe_uniprot_raw", "art_probe_uniprot_fasta"],
            "raw_response_artifact_id": "art_probe_uniprot_raw",
            "parsed_fasta_artifact_id": "art_probe_uniprot_fasta",
        },
    ]
    toolchain_receipts = [
        {
            "toolchain_record_id": "toolchain_record_probe_mafft",
            **_toolchain_identity_fields("mafft"),
            "tool": "mafft",
            "operation_id": "op_probe_mafft",
            "job_id": "job_probe_mafft",
            "status": "completed",
            "artifact_ids": ["art_probe_mafft_alignment"],
        },
        {
            "toolchain_record_id": "toolchain_record_probe_hmmbuild",
            **_toolchain_identity_fields("hmmbuild"),
            "tool": "hmmbuild",
            "operation_id": "op_probe_hmmbuild",
            "job_id": "job_probe_hmmbuild",
            "status": "completed",
            "artifact_ids": ["art_probe_hmm_model"],
        },
        {
            "toolchain_record_id": "toolchain_record_probe_cdhit",
            **_toolchain_identity_fields("cd-hit"),
            "tool": "cd-hit",
            "operation_id": "op_probe_cdhit",
            "job_id": "job_probe_cdhit",
            "status": "completed",
            "artifact_ids": [
                "art_probe_cdhit_fasta",
                "art_probe_cdhit_membership",
            ],
            "parameters": {"identity": 1.0, "mode": "protein"},
        },
        {
            "toolchain_record_id": "toolchain_record_probe_hmmalign",
            **_toolchain_identity_fields("hmmalign"),
            "tool": "hmmalign",
            "operation_id": "op_probe_hmmalign",
            "job_id": "job_probe_hmmalign",
            "status": "completed",
            "artifact_ids": ["art_probe_hmmalign_alignment"],
        },
    ]
    provider_by_name = {receipt["provider"]: receipt for receipt in provider_receipts}
    toolchain_by_tool = {receipt["tool"]: receipt for receipt in toolchain_receipts}
    artifact_roles = {
        "source_snapshot": "art_probe_source_snapshot",
        "ncbi_raw_response": "art_probe_ncbi_raw",
        "ncbi_fasta": "art_probe_ncbi_fasta",
        "mafft_alignment": "art_probe_mafft_alignment",
        "hmm_model": "art_probe_hmm_model",
        "uniprot_raw_response": "art_probe_uniprot_raw",
        "uniprot_fasta": "art_probe_uniprot_fasta",
        "cdhit_clustered_fasta": "art_probe_cdhit_fasta",
        "cdhit_membership": "art_probe_cdhit_membership",
        "hmmalign_alignment": "art_probe_hmmalign_alignment",
    }
    operation_roles = {
        "ncbi_fetch": "op_probe_ncbi",
        "reference_alignment": "op_probe_mafft",
        "hmm_build": "op_probe_hmmbuild",
        "uniprot_fetch": "op_probe_uniprot",
        "candidate_cluster": "op_probe_cdhit",
        "candidate_alignment": "op_probe_hmmalign",
    }
    sequence_digests = sorted(
        (
            _digest_bytes(beta_globin.encode("ascii")),
            _digest_bytes(alpha_globin.encode("ascii")),
        )
    )
    probe = {
        "schema_id": KNOWN_POSITIVE_PROBE_SCHEMA_ID,
        "probe_id": KNOWN_POSITIVE_PROBE_ID,
        "status": "passed",
        "bounded": True,
        "formal_data_isolated": True,
        "artifact_ids": list(contents),
        "operation_roles": operation_roles,
        "artifact_roles": artifact_roles,
        "isolation": {
            "schema_id": "aox_known_positive_probe_isolation@1",
            "session_id": session_id,
            "task_id": task_id,
            "task_finish_ref": "doc_probe_task_finish",
            "sandbox_run_id": sandbox_run_id,
            "sandbox_workspace_id": sandbox_workspace_id,
            "source_snapshot_artifact_id": "art_probe_source_snapshot",
            "source_snapshot_digest": source_snapshot_digest,
            "source_snapshot_artifact_digest": source_snapshot_artifact_digest,
            "hpc_workspace_id": hpc_workspace_id,
            "controlled_operation_count": 6,
        },
        "known_positive_identity": {
            "ncbi_accessions": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
            "uniprot_accessions": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
            "cross_provider_sequence_digest": canonical_digest(sequence_digests),
        },
        "checks": [
            {
                "check_id": "ncbi_globin_pair",
                "category": "provider",
                "status": "passed",
                "receipt_id": provider_by_name["ncbi"]["provider_record_id"],
            },
            {
                "check_id": "uniprot_globin_pair",
                "category": "provider",
                "status": "passed",
                "receipt_id": provider_by_name["uniprot"]["provider_record_id"],
            },
            *(
                {
                    "check_id": f"hpc_{tool_name.replace('-', '')}",
                    "category": "hpc",
                    "status": "passed",
                    "receipt_id": toolchain_by_tool[tool_name]["toolchain_record_id"],
                }
                for tool_name in ("mafft", "hmmbuild", "cd-hit", "hmmalign")
            ),
        ],
        "provider_receipts": provider_receipts,
        "toolchain_receipts": toolchain_receipts,
    }
    approvals = [
        {
            "approval_id": f"approval_{operation['operation_id']}",
            "operation_id": operation["operation_id"],
            "operation_identity_digest": operation["operation_identity_digest"],
            "decision": "approved",
        }
        for operation in operations
    ]
    return {
        "artifacts": artifacts,
        "operations": operations,
        "approvals": approvals,
        "probe": probe,
    }


def _apply_hmmer_upstream_empty_fixture(
    artifact_root: Path,
    evidence: dict[str, object],
) -> None:
    reason = "no_hmmer_hits"
    empty_hmmer_body = (
        json.dumps(
            {"database": "refprot", "hits": []},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    raw_page_digest = _digest_bytes(empty_hmmer_body)
    empty_hmmer_envelope = (
        json.dumps(
            {
                "schema_id": "provider_raw_http_response_set@1",
                "provider": "ebi_hmmer",
                "operation": "bio.hmmer_search",
                "responses": [
                    {
                        "ordinal": 1,
                        "phase": "results",
                        "status_code": 200,
                        "headers": {},
                        "body_encoding": "base64",
                        "body_base64": base64.b64encode(empty_hmmer_body).decode(
                            "ascii"
                        ),
                        "body_digest": raw_page_digest,
                        "size_bytes": len(empty_hmmer_body),
                    }
                ],
            },
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )
    parsed_output = io.StringIO(newline="")
    parsed_writer = csv.DictWriter(
        parsed_output,
        fieldnames=list(aox_hmmer.INPUT_COLUMNS),
        lineterminator="\n",
    )
    parsed_writer.writeheader()
    parsed_bytes = parsed_output.getvalue().encode("utf-8")
    score_filter_result = aox_hmmer.parse_and_filter_csv(parsed_bytes)
    score_filtered_bytes = score_filter_result.to_csv().encode("utf-8")
    post_uniprot_filtered_bytes = (
        ",".join(aox_sequence_join.OUTPUT_COLUMNS) + "\n"
    ).encode("utf-8")
    target_bytes = b""
    scoring_reference_artifact = next(
        artifact
        for artifact in evidence["artifacts"]
        if artifact["artifact_id"] == "art_scoring_reference"
    )
    scoring_reference_bytes = (
        artifact_root / str(scoring_reference_artifact["relative_path"])
    ).read_bytes()
    scoring_input_result = aox_reference.assemble_scoring_input(
        scoring_reference_bytes,
        target_bytes,
        expected_scoring_reference_input_digest=_digest_bytes(scoring_reference_bytes),
        expected_target_input_digest=_digest_bytes(target_bytes),
    )
    scoring_input_bytes = scoring_input_result.to_fasta().encode("utf-8")
    scoring_result = aox_motif.score_aligned_fasta(scoring_reference_bytes)
    scored_bytes = scoring_result.to_csv().encode("utf-8")
    candidate_bytes = b""
    membership_bytes = (",".join(aox_similarity.MEMBERSHIP_COLUMNS) + "\n").encode(
        "utf-8"
    )
    graph = aox_similarity.build_similarity_graph(
        candidate_bytes,
        membership_bytes,
        threshold_ppm=750_000,
        empty_result_reason=reason,
    )

    scoring_input_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_scoring_input",
        content=scoring_input_bytes,
    )
    hmmer_response_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_ebi_hmmer_response",
        content=empty_hmmer_envelope,
    )
    parsed_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_hmmer_parsed_hits",
        content=parsed_bytes,
    )
    score_filtered_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_hmmer_score_filtered_accessions",
        content=score_filtered_bytes,
    )
    post_uniprot_filtered_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_post_uniprot_filtered_hits",
        content=post_uniprot_filtered_bytes,
    )
    target_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_target_sequences",
        content=target_bytes,
    )
    scoring_alignment_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_alignment",
        content=scoring_reference_bytes,
    )
    scored_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_scores",
        content=scored_bytes,
    )
    candidate_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_candidates",
        content=candidate_bytes,
    )
    _attach_typed_empty_validation(
        evidence,
        artifact_id="art_target_sequences",
        reason=reason,
        derivation_contract_id=AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID,
    )
    _attach_typed_empty_validation(
        evidence,
        artifact_id="art_candidates",
        reason=reason,
        derivation_contract_id="aox_motif_candidate_filter@1",
    )
    membership_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_membership",
        content=membership_bytes,
    )
    nodes_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_nodes",
        content=graph.nodes_csv().encode("utf-8"),
    )
    edges_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_edges",
        content=graph.edges_csv().encode("utf-8"),
    )
    manifest_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_graph_manifest",
        content=graph.manifest_json().encode("utf-8"),
    )

    omitted_operation_ids = {
        "op_uniprot",
        "op_post_uniprot_filter",
        "op_hmmalign",
        "op_cdhit",
    }
    evidence["operations"] = [
        operation
        for operation in evidence["operations"]
        if operation["operation_id"] not in omitted_operation_ids
    ]
    upstream_materialization = _operation(
        "op_upstream_empty_materialization",
        inputs=[("art_hmmer_score_filtered_accessions", score_filtered_digest)],
        outputs=[
            ("art_post_uniprot_filtered_hits", post_uniprot_filtered_digest),
            ("art_target_sequences", target_digest),
        ],
    )
    upstream_materialization["kind"] = AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID
    upstream_materialization["parameters"] = {
        "reason": reason,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
    }
    _refresh_sandbox_calculation_identity(upstream_materialization)
    empty_target_scoring = _operation(
        "op_empty_target_scoring",
        inputs=[
            ("art_scoring_input", scoring_input_digest),
            ("art_target_sequences", target_digest),
        ],
        outputs=[("art_alignment", scoring_alignment_digest)],
    )
    empty_target_scoring["kind"] = AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID
    empty_target_scoring["parameters"] = {
        "reason": reason,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
    }
    _refresh_sandbox_calculation_identity(empty_target_scoring)
    empty_membership = _operation(
        "op_empty_membership",
        inputs=[("art_candidates", candidate_digest)],
        outputs=[("art_membership", membership_digest)],
    )
    empty_membership["kind"] = AOX_EMPTY_MEMBERSHIP_ID
    empty_membership["parameters"] = {"identity_threshold_ppm": 750_000}
    _refresh_sandbox_calculation_identity(empty_membership)
    evidence["operations"].extend(
        [upstream_materialization, empty_target_scoring, empty_membership]
    )

    operation_by_id = {
        operation["operation_id"]: operation for operation in evidence["operations"]
    }
    operation_by_id["op_scoring_input_assembly"]["parameters"] = {
        "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
        "target_count": 0,
    }
    operation_by_id["op_score"]["inputs"] = [
        {
            "artifact_id": "art_alignment",
            "content_digest": scoring_alignment_digest,
        }
    ]
    operation_by_id["op_score"]["outputs"] = [
        {"artifact_id": "art_scores", "content_digest": scored_digest}
    ]
    operation_by_id["op_candidate_filter"]["inputs"] = [
        {"artifact_id": "art_scores", "content_digest": scored_digest},
        {"artifact_id": "art_target_sequences", "content_digest": target_digest},
    ]
    operation_by_id["op_candidate_filter"]["outputs"] = [
        {"artifact_id": "art_candidates", "content_digest": candidate_digest}
    ]
    operation_by_id["op_similarity"]["inputs"] = [
        {"artifact_id": "art_candidates", "content_digest": candidate_digest},
        {"artifact_id": "art_membership", "content_digest": membership_digest},
    ]
    operation_by_id["op_similarity"]["outputs"] = [
        {"artifact_id": "art_nodes", "content_digest": nodes_digest},
        {"artifact_id": "art_edges", "content_digest": edges_digest},
        {"artifact_id": "art_graph_manifest", "content_digest": manifest_digest},
    ]

    removed_artifact_ids = {"art_uniprot_candidates", "art_uniprot_metadata"}
    evidence["artifacts"] = [
        artifact
        for artifact in evidence["artifacts"]
        if artifact["artifact_id"] not in removed_artifact_ids
    ]
    artifact_by_id = {
        artifact["artifact_id"]: artifact for artifact in evidence["artifacts"]
    }
    artifact_by_id["art_alignment"]["provenance"] = {
        "operation_id": "op_empty_target_scoring",
        "calculation_id": AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID,
    }
    for artifact_id in ("art_post_uniprot_filtered_hits", "art_target_sequences"):
        artifact_by_id[artifact_id]["provenance"] = {
            "operation_id": "op_upstream_empty_materialization",
            "calculation_id": AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID,
        }
    artifact_by_id["art_membership"]["provenance"] = {
        "operation_id": "op_empty_membership",
        "schema_id": aox_similarity.MEMBERSHIP_SCHEMA_ID,
    }

    provider_by_name = {
        provider["provider"]: provider for provider in evidence["provider_identities"]
    }
    provider_by_name["ebi_hmmer"]["response_digest"] = raw_page_digest
    dependency = {
        "upstream_provider_record_id": "provider_record_ebi_hmmer",
        "downstream_provider_record_id": "provider_record_uniprot_upstream_empty",
        "derivation_id": aox_hmmer.CONTRACT_ID,
        "upstream_response_artifact_ids": ["art_ebi_hmmer_response"],
        "derivation_operation_id": "op_pre_uniprot_score_filter",
        "parsed_hit_artifact_id": "art_hmmer_parsed_hits",
        "parsed_hit_artifact_digest": parsed_digest,
        "derived_accession_artifact_id": ("art_hmmer_score_filtered_accessions"),
        "derived_accession_artifact_digest": score_filtered_digest,
        "derivation_contract_digest": aox_hmmer.CONTRACT_DIGEST,
        "derivation_implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
        "derived_accessions": [],
        "derived_accessions_digest": canonical_digest([]),
        "terminal_empty_reason": reason,
    }
    decision_material = {
        "reason": reason,
        "upstream_provider_record_id": dependency["upstream_provider_record_id"],
        "derivation_operation_id": dependency["derivation_operation_id"],
        "derived_accession_artifact_id": dependency["derived_accession_artifact_id"],
        "derived_accession_artifact_digest": dependency[
            "derived_accession_artifact_digest"
        ],
        "derived_accessions_digest": dependency["derived_accessions_digest"],
    }
    skip_payload = {
        "schema_id": "provider_upstream_empty_receipt@1",
        "provider_record_id": "provider_record_uniprot_upstream_empty",
        "provider": "uniprot",
        "status": "upstream_empty",
        "canonical_ref_kind": "upstream_empty",
        "operation_id": None,
        "invocation_id": None,
        "provider_io_performed": False,
        "cache_consulted": False,
        **decision_material,
        "decision_input_digest": canonical_digest(decision_material),
    }
    skip_payload["skip_receipt_digest"] = canonical_digest(skip_payload)
    _write_artifact(
        artifact_root,
        "formal/provider/uniprot-upstream-empty.json",
        canonical_json_bytes(skip_payload) + b"\n",
    )
    skip_artifact = {
        "artifact_id": "art_uniprot_upstream_empty",
        "relative_path": "formal/provider/uniprot-upstream-empty.json",
        "scope": "formal",
        "origin": "attestation",
        "kind": "provider_receipt",
        "provenance": {
            "provider_record_id": "provider_record_uniprot_upstream_empty",
            "upstream_provider_record_id": "provider_record_ebi_hmmer",
            "derivation_operation_id": "op_pre_uniprot_score_filter",
            "skip_receipt_digest": skip_payload["skip_receipt_digest"],
        },
    }
    evidence["artifacts"].append(skip_artifact)
    skipped_uniprot_provider = {
        "provider_record_id": "provider_record_uniprot_upstream_empty",
        "provider": "uniprot",
        "status": "upstream_empty",
        "canonical_ref_kind": "upstream_empty",
        "invocation_id": None,
        "operation_id": None,
        "cache_hit": False,
        "request_digest": None,
        "response_digest": None,
        "artifact_ids": ["art_uniprot_upstream_empty"],
        "source_ref_ids": [],
        "reason": reason,
        "skip_receipt_digest": skip_payload["skip_receipt_digest"],
        "provider_io_performed": False,
        "cache_consulted": False,
    }
    evidence["provider_identities"] = [
        skipped_uniprot_provider if provider["provider"] == "uniprot" else provider
        for provider in evidence["provider_identities"]
    ]
    dependency.update(
        {
            "skip_receipt_digest": skip_payload["skip_receipt_digest"],
            "skip_artifact_id": "art_uniprot_upstream_empty",
        }
    )

    evidence["toolchain_identities"] = [
        toolchain
        for toolchain in evidence["toolchain_identities"]
        if toolchain["tool"] in {"mafft", "hmmbuild"}
    ]
    evidence["report"]["artifact_ids"] = [
        artifact_id
        for artifact_id in evidence["report"]["artifact_ids"]
        if artifact_id not in removed_artifact_ids
    ]
    scientific_checks = evidence["scientific_checks"]
    scientific_checks.pop("sequence_join")
    scientific_checks["scoring"].update(
        {
            "alignment_artifact_id": "art_alignment",
            "scored_artifact_id": "art_scores",
            "input_digest": scoring_result.alignment.input_digest,
        }
    )
    scientific_checks["similarity"].update(
        {
            "empty_result_reason": reason,
            "candidate_fasta_digest": graph.sequences.input_digest,
            "membership_digest": graph.membership.input_digest,
        }
    )
    scientific_checks["aox_chain"] = {
        "literature_provider_record_id": "provider_record_pubmed",
        "operation_roles": {
            "ncbi_fetch": "op_ncbi",
            "hmm_reference_set_selection": "op_hmm_reference_set_selection",
            "scoring_reference_selection": "op_scoring_reference_selection",
            "reference_alignment": "op_align",
            "hmm_build": "op_hmmbuild",
            "hmmer_search": "op_ebi_hmmer",
            "pre_uniprot_score_filter": "op_pre_uniprot_score_filter",
            "scoring_input_assembly": "op_scoring_input_assembly",
            "upstream_empty_materialization": ("op_upstream_empty_materialization"),
            "empty_target_scoring_materialization": "op_empty_target_scoring",
            "motif_score": "op_score",
            "candidate_filter": "op_candidate_filter",
            "empty_membership": "op_empty_membership",
            "similarity": "op_similarity",
        },
        "provider_dependencies": [dependency],
        "artifact_roles": {
            "literature_evidence": "art_pubmed_response",
            "ncbi_provider_sequences": "art_ncbi_provider_sequences",
            "hmm_reference_set": "art_hmm_reference_set",
            "scoring_reference": "art_scoring_reference",
            "scoring_input": "art_scoring_input",
            "reference_alignment": "art_reference_alignment",
            "hmm_model": "art_hmm_model",
            "hmmer_response": "art_ebi_hmmer_response",
            "hmmer_parsed_hits": "art_hmmer_parsed_hits",
            "hmmer_score_filtered_accessions": ("art_hmmer_score_filtered_accessions"),
            "post_uniprot_filtered_hits": "art_post_uniprot_filtered_hits",
            "target_sequences": "art_target_sequences",
            "scoring_alignment": "art_alignment",
            "motif_scores": "art_scores",
            "candidates": "art_candidates",
            "cdhit_membership": "art_membership",
            "graph_nodes": "art_nodes",
            "graph_edges": "art_edges",
            "graph_manifest": "art_graph_manifest",
        },
        "excluded_scoring_sequence_ids": [aox_motif.REFERENCE_ACCESSION],
        "empty_branch": {
            "schema_id": "aox_empty_branch@1",
            "stage": "pre_uniprot_score_filter",
            "reason": reason,
            "trigger_artifact_id": "art_hmmer_score_filtered_accessions",
            "trigger_artifact_digest": score_filtered_digest,
            "observed_count_before": 0,
            "observed_count_after": 0,
            "derivation_operation_id": "op_pre_uniprot_score_filter",
            "skip_provider_record_id": "provider_record_uniprot_upstream_empty",
            "omitted_controlled_roles": [
                "uniprot_fetch",
                "candidate_alignment",
                "cdhit",
            ],
            "empty_materialization_operation_id": ("op_upstream_empty_materialization"),
            "empty_membership_operation_id": "op_empty_membership",
        },
    }
    evidence["scientific_outcome"] = {
        "status": "empty",
        "candidate_count": 0,
        "empty_result_reason": reason,
        "cutover_eligible": True,
    }

    operation_by_id["op_ebi_hmmer"]["outputs"] = [
        {
            "artifact_id": "art_ebi_hmmer_response",
            "content_digest": hmmer_response_digest,
        },
        {"artifact_id": "art_hmmer_parsed_hits", "content_digest": parsed_digest},
    ]
    operation_by_id["op_pre_uniprot_score_filter"]["inputs"] = [
        {"artifact_id": "art_hmmer_parsed_hits", "content_digest": parsed_digest}
    ]
    operation_by_id["op_pre_uniprot_score_filter"]["outputs"] = [
        {
            "artifact_id": "art_hmmer_score_filtered_accessions",
            "content_digest": score_filtered_digest,
        }
    ]
    _refresh_fixture_operation_identities(evidence)


def _valid_evidence(
    artifact_root: Path,
    *,
    attempt_kind: str,
    clean_world: dict[str, object],
    run_suffix: str | None = None,
    scientific_branch: str = "nonempty",
    effective_config: dict[str, object] | None = None,
) -> dict[str, object]:
    effective_config_payload = json.loads(
        json.dumps(effective_config or _effective_config())
    )
    if attempt_kind == "fault" and effective_config is None:
        effective_config_payload["driver"]["approval_mode"] = "chrome-once"
        effective_config_payload["driver"]["ui_dist_digest"] = _digest("ui-dist")
    effective_config_digest = canonical_digest(effective_config_payload)
    alignment_bytes = GOLDEN_ALIGNMENT.read_bytes()
    scoring_result = aox_motif.score_aligned_fasta(alignment_bytes)
    scored_bytes = scoring_result.to_csv().encode("utf-8")
    aligned_records = {
        record.sequence_id: record.sequence
        for record in scoring_result.alignment.records
    }
    normalized_hit_sequences = {
        sequence_id.strip().upper(): sequence.replace("-", "").replace(".", "")
        for sequence_id, sequence in aligned_records.items()
        if sequence_id != aox_motif.REFERENCE_ACCESSION
    }
    hit_ids = sorted(normalized_hit_sequences)
    accession_by_hit_id = dict(zip(hit_ids, ("K3VE05", "Q9XYZ1"), strict=True))
    hit_id_by_accession = {
        accession: hit_id for hit_id, accession in accession_by_hit_id.items()
    }
    candidate_ids = [
        row.sequence_id
        for row in scoring_result.rows
        if row.passes_motif_rule and row.sequence_id != aox_motif.REFERENCE_ACCESSION
    ]
    report_bytes = (
        b"# AOX/HMM report\n\nThe formula-derived motif result is reproducible.\n"
        if attempt_kind == "positive"
        else b"# AOX/HMM fault evidence\n\nThe required-chain byte fault failed closed.\n"
    )
    hpc_workspace_label = str(clean_world["hpc_workspace_label"])
    probe_fixture = _known_positive_probe_fixture(
        artifact_root,
        hpc_workspace_label=hpc_workspace_label,
    )
    pubmed_request_digest = _digest("pubmed-request")
    pubmed_response_digest = _digest("pubmed-provider-response")
    pubmed_bytes = (
        canonical_json_bytes(
            {
                "schema_id": "provider_web_evidence@1",
                "provider": "pubmed",
                "request_digest": pubmed_request_digest,
                "response_digest": pubmed_response_digest,
                "citations": [{"pmid": "12345678", "title": "AOX evidence"}],
            }
        )
        + b"\n"
    )
    ncbi_bytes = _ncbi_reference_set()
    ncbi_digest = _digest_bytes(ncbi_bytes)
    hmm_reference_selection = aox_reference.select_hmm_reference_set(
        ncbi_bytes,
        expected_input_digest=ncbi_digest,
    )
    hmm_reference_set_bytes = hmm_reference_selection.to_fasta().encode("utf-8")
    scoring_reference_selection = aox_reference.select_scoring_reference(
        ncbi_bytes,
        expected_input_digest=ncbi_digest,
    )
    scoring_reference_bytes = scoring_reference_selection.to_fasta().encode("utf-8")
    ebi_hmmer_body = (
        json.dumps(
            {
                "database": "refprot",
                "hits": [
                    {
                        "acc": accession_by_hit_id[hit_id],
                        "target": hit_id,
                    }
                    for hit_id in hit_ids
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    parsed_hit_rows: list[dict[str, str]] = []
    raw_page_digest = _digest_bytes(ebi_hmmer_body)
    ebi_hmmer_bytes = (
        json.dumps(
            {
                "schema_id": "provider_raw_http_response_set@1",
                "provider": "ebi_hmmer",
                "operation": "bio.hmmer_search",
                "responses": [
                    {
                        "ordinal": 1,
                        "phase": "results",
                        "status_code": 200,
                        "headers": {},
                        "body_encoding": "base64",
                        "body_base64": base64.b64encode(ebi_hmmer_body).decode("ascii"),
                        "body_digest": raw_page_digest,
                        "size_bytes": len(ebi_hmmer_body),
                    }
                ],
            },
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )
    for hit_index, hit_id in enumerate(hit_ids):
        accession = accession_by_hit_id[hit_id]
        score_numeric = f"25{hit_index}.1"
        digest_payload: dict[str, object] = {
            "target": hit_id,
            "accession": accession,
            "evalue": "0.000001",
            "score": score_numeric,
            "page": 1,
            "hit_index": hit_index,
            "evalue_numeric": "0.000001",
            "score_numeric": score_numeric,
            "raw_page_digest": raw_page_digest,
            "raw_hit_digest": _digest(f"ebi-hmmer-hit:{accession}"),
        }
        parsed_row_digest = _digest_bytes(
            (json.dumps(digest_payload, sort_keys=True, indent=2) + "\n").encode(
                "utf-8"
            )
        )
        parsed_hit_rows.append(
            {
                **{key: str(value) for key, value in digest_payload.items()},
                "parsed_row_digest": parsed_row_digest,
            }
        )
    parsed_hit_output = io.StringIO(newline="")
    parsed_hit_writer = csv.DictWriter(
        parsed_hit_output,
        fieldnames=list(aox_hmmer.INPUT_COLUMNS),
        lineterminator="\n",
    )
    parsed_hit_writer.writeheader()
    parsed_hit_writer.writerows(parsed_hit_rows)
    parsed_hit_bytes = parsed_hit_output.getvalue().encode("utf-8")
    score_filter_result = aox_hmmer.parse_and_filter_csv(parsed_hit_bytes)
    score_filtered_accession_bytes = score_filter_result.to_csv().encode("utf-8")
    derived_accessions = list(score_filter_result.accessions)
    uniprot_retrieved_at = "2026-07-17T00:00:00+00:00"
    uniprot_release = "2026_03"
    uniprot_release_date = "2026-06-17"
    uniprot_page_response_digest = _digest("uniprot-page-response")
    uniprot_bytes = "".join(
        f">{accession} {accession}_AOX\n"
        f"{normalized_hit_sequences[hit_id_by_accession[accession]]}\n"
        for accession in derived_accessions
    ).encode("utf-8")
    uniprot_metadata_records: list[dict[str, object]] = []
    for accession in derived_accessions:
        sequence = normalized_hit_sequences[hit_id_by_accession[accession]]
        sequence_digest = _digest_bytes(sequence.encode("ascii"))
        identifier = f"{accession}_AOX"
        entry_type = "UniProtKB reviewed (Swiss-Prot)"
        provider_metadata = {
            "primaryAccession": accession,
            "secondaryAccessions": [],
            "uniProtkbId": identifier,
            "entryType": entry_type,
            "entryAudit": {"entryVersion": 1, "sequenceVersion": 1},
        }
        provider_result = {
            **provider_metadata,
            "sequence": {"value": sequence, "length": len(sequence)},
        }
        uniprot_metadata_records.append(
            {
                "requested_accession": accession,
                "primary_accession": accession,
                "uniprot_identifier": identifier,
                "reviewed": True,
                "entry_type": entry_type,
                "uniprot_release": uniprot_release,
                "uniprot_release_date": uniprot_release_date,
                "retrieved_at": uniprot_retrieved_at,
                "entry_version": 1,
                "sequence_version": 1,
                "sequence_length": len(sequence),
                "sequence_digest": sequence_digest,
                "response_digest": uniprot_page_response_digest,
                "record_digest": _digest_bytes(
                    (
                        json.dumps(provider_result, sort_keys=True, indent=2) + "\n"
                    ).encode("utf-8")
                ),
                "mapping_annotations": [
                    {
                        "annotation_type": "provider_identity_mapping",
                        "source_database": "requested_identifier",
                        "source_accession": accession,
                        "target_database": "uniprotkb",
                        "target_accession": accession,
                        "relationship": "resolves_to_primary_accession",
                        "identity_replaced": False,
                    }
                ],
                "provider_metadata": provider_metadata,
            }
        )
    uniprot_aggregate_response_digest = _digest_bytes(
        (
            json.dumps(
                [uniprot_page_response_digest],
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
    )
    uniprot_metadata_bytes = (
        json.dumps(
            {
                "provider": "uniprot",
                "database": "uniprotkb",
                "fields": [
                    "accession",
                    "id",
                    "sequence",
                    "reviewed",
                    "sequence_version",
                    "version",
                ],
                "batch_size": 100,
                "identity_contract_id": "uniprot_primary_sequence_identity@1",
                "requested_accessions": derived_accessions,
                "records": uniprot_metadata_records,
                "warnings": [],
                "retrieved_at": uniprot_retrieved_at,
                "uniprot_release": uniprot_release,
                "uniprot_release_date": uniprot_release_date,
                "aggregate_response_digest": uniprot_aggregate_response_digest,
                "source_sequence_identity_count": 0,
                "sequence_mismatch_resolution_count": 0,
                "api_version": "rest.uniprot.org@2026-03",
            },
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )
    sequence_join_result = aox_sequence_join.join_score_filtered_accessions(
        score_filtered_accession_bytes,
        uniprot_bytes,
        uniprot_metadata_bytes,
        expected_contract_id=aox_sequence_join.CONTRACT_ID,
        expected_contract_digest=aox_sequence_join.CONTRACT_DIGEST,
        expected_implementation_digest=aox_sequence_join.IMPLEMENTATION_DIGEST,
        expected_hmmer_contract_id=aox_hmmer.CONTRACT_ID,
        expected_hmmer_contract_digest=aox_hmmer.CONTRACT_DIGEST,
        expected_hmmer_implementation_digest=aox_hmmer.IMPLEMENTATION_DIGEST,
        expected_score_filtered_csv_digest=_digest_bytes(
            score_filtered_accession_bytes
        ),
        expected_uniprot_fasta_digest=_digest_bytes(uniprot_bytes),
        expected_uniprot_metadata_digest=_digest_bytes(uniprot_metadata_bytes),
    )
    post_uniprot_filtered_bytes = sequence_join_result.hits_csv().encode("utf-8")
    target_sequence_bytes = sequence_join_result.target_fasta().encode("utf-8")
    scoring_input_assembly = aox_reference.assemble_scoring_input(
        scoring_reference_bytes,
        target_sequence_bytes,
        expected_scoring_reference_input_digest=_digest_bytes(scoring_reference_bytes),
        expected_target_input_digest=_digest_bytes(target_sequence_bytes),
    )
    scoring_input_bytes = scoring_input_assembly.to_fasta().encode("utf-8")
    candidate_bytes = "".join(
        f">{item}\n{aligned_records[item]}\n" for item in candidate_ids
    ).encode("utf-8")
    membership_bytes = (
        "cluster_id,member_id,representative_id,is_representative,"
        "identity_to_representative,member_length\n"
        + "".join(
            f"cluster_{index},{item},{item},true,1.000000,"
            f"{len(aligned_records[item])}\n"
            for index, item in enumerate(candidate_ids)
        )
    ).encode("utf-8")
    reference_alignment_bytes = hmm_reference_set_bytes
    hmm_model_bytes = b"HMMER3/f [aox-test]\nNAME AOX_test\n//\n"
    graph = aox_similarity.build_similarity_graph(
        candidate_bytes,
        membership_bytes,
        threshold_ppm=750_000,
    )
    alignment_digest = _write_artifact(
        artifact_root, "formal/scoring-alignment.fasta", alignment_bytes
    )
    scored_digest = _write_artifact(
        artifact_root, "formal/motif-scores.csv", scored_bytes
    )
    report_digest = _write_artifact(artifact_root, "formal/report.md", report_bytes)
    pubmed_digest = _write_artifact(
        artifact_root, "formal/provider/pubmed-response.json", pubmed_bytes
    )
    ncbi_digest = _write_artifact(
        artifact_root, "formal/provider/ncbi-provider-sequences.fasta", ncbi_bytes
    )
    hmm_reference_set_digest = _write_artifact(
        artifact_root,
        "formal/calculation/AOX-ref21.fasta",
        hmm_reference_set_bytes,
    )
    scoring_reference_digest = _write_artifact(
        artifact_root,
        "formal/calculation/AOX-coordinate-reference-AAB57849.1.fasta",
        scoring_reference_bytes,
    )
    scoring_input_digest = _write_artifact(
        artifact_root,
        "formal/calculation/AOX-scoring-input.fasta",
        scoring_input_bytes,
    )
    reference_alignment_digest = _write_artifact(
        artifact_root,
        "formal/toolchain/reference-alignment.fasta",
        reference_alignment_bytes,
    )
    hmm_model_digest = _write_artifact(
        artifact_root,
        "formal/toolchain/aox-reference.hmm",
        hmm_model_bytes,
    )
    ebi_hmmer_artifact_digest = _write_artifact(
        artifact_root,
        "formal/provider/ebi-hmmer-response.json",
        ebi_hmmer_bytes,
    )
    parsed_hit_digest = _write_artifact(
        artifact_root,
        "formal/provider/ebi-hmmer-parsed-hits.csv",
        parsed_hit_bytes,
    )
    score_filtered_accession_digest = _write_artifact(
        artifact_root,
        "formal/calculation/hmmer-score-filtered-accessions.csv",
        score_filtered_accession_bytes,
    )
    uniprot_digest = _write_artifact(
        artifact_root, "formal/provider/uniprot-candidates.fasta", uniprot_bytes
    )
    uniprot_metadata_digest = _write_artifact(
        artifact_root,
        "formal/provider/uniprot-metadata.json",
        uniprot_metadata_bytes,
    )
    post_uniprot_filtered_digest = _write_artifact(
        artifact_root,
        "formal/calculation/hits-len650-700-200.csv",
        post_uniprot_filtered_bytes,
    )
    target_sequence_digest = _write_artifact(
        artifact_root,
        "formal/calculation/target-sequences.fasta",
        target_sequence_bytes,
    )
    candidate_digest = _write_artifact(
        artifact_root, "formal/candidates.fasta", candidate_bytes
    )
    membership_digest = _write_artifact(
        artifact_root, "formal/cdhit-membership.csv", membership_bytes
    )
    nodes_digest = _write_artifact(
        artifact_root, "formal/graph-nodes.csv", graph.nodes_csv().encode("utf-8")
    )
    edges_digest = _write_artifact(
        artifact_root, "formal/graph-edges.csv", graph.edges_csv().encode("utf-8")
    )
    manifest_digest = _write_artifact(
        artifact_root,
        "formal/graph-manifest.json",
        graph.manifest_json().encode("utf-8"),
    )
    artifacts = [
        {
            "artifact_id": "art_pubmed_response",
            "relative_path": "formal/provider/pubmed-response.json",
            "scope": "formal",
            "origin": "engine_invocation",
            "kind": "provider_evidence",
            "provenance": {
                "invocation_id": "invocation_pubmed",
                "provider": "pubmed",
                "task_id": "task_research",
                "lane_id": "lane_research",
            },
        },
        {
            "artifact_id": "art_ncbi_provider_sequences",
            "relative_path": "formal/provider/ncbi-provider-sequences.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "provider_evidence",
            "provenance": {"operation_id": "op_ncbi", "provider": "ncbi"},
        },
        {
            "artifact_id": "art_hmm_reference_set",
            "relative_path": "formal/calculation/AOX-ref21.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {
                "operation_id": "op_hmm_reference_set_selection",
                "calculation_id": (
                    aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
                ),
            },
        },
        {
            "artifact_id": "art_scoring_reference",
            "relative_path": (
                "formal/calculation/AOX-coordinate-reference-AAB57849.1.fasta"
            ),
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {
                "operation_id": "op_scoring_reference_selection",
                "calculation_id": (
                    aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
                ),
                "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
            },
        },
        {
            "artifact_id": "art_scoring_input",
            "relative_path": "formal/calculation/AOX-scoring-input.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {
                "operation_id": "op_scoring_input_assembly",
                "calculation_id": aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
            },
        },
        {
            "artifact_id": "art_reference_alignment",
            "relative_path": "formal/toolchain/reference-alignment.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {"operation_id": "op_align", "tool": "mafft"},
        },
        {
            "artifact_id": "art_hmm_model",
            "relative_path": "formal/toolchain/aox-reference.hmm",
            "scope": "formal",
            "origin": "operation",
            "kind": "model",
            "provenance": {"operation_id": "op_hmmbuild", "tool": "hmmbuild"},
        },
        {
            "artifact_id": "art_ebi_hmmer_response",
            "relative_path": "formal/provider/ebi-hmmer-response.json",
            "scope": "formal",
            "origin": "operation",
            "kind": "provider_evidence",
            "provenance": {
                "operation_id": "op_ebi_hmmer",
                "provider": "ebi_hmmer",
            },
        },
        {
            "artifact_id": "art_hmmer_parsed_hits",
            "relative_path": "formal/provider/ebi-hmmer-parsed-hits.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_ebi_hmmer",
                "provider": "ebi_hmmer",
                "provider_artifact_kind": "provider_parsed",
            },
        },
        {
            "artifact_id": "art_hmmer_score_filtered_accessions",
            "relative_path": ("formal/calculation/hmmer-score-filtered-accessions.csv"),
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_pre_uniprot_score_filter",
                "derivation_id": aox_hmmer.CONTRACT_ID,
            },
        },
        {
            "artifact_id": "art_uniprot_candidates",
            "relative_path": "formal/provider/uniprot-candidates.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "provider_evidence",
            "provenance": {"operation_id": "op_uniprot", "provider": "uniprot"},
        },
        {
            "artifact_id": "art_uniprot_metadata",
            "relative_path": "formal/provider/uniprot-metadata.json",
            "scope": "formal",
            "origin": "operation",
            "kind": "provider_evidence",
            "provenance": {
                "operation_id": "op_uniprot",
                "provider": "uniprot",
                "identity_contract_id": "uniprot_primary_sequence_identity@1",
            },
        },
        {
            "artifact_id": "art_post_uniprot_filtered_hits",
            "relative_path": "formal/calculation/hits-len650-700-200.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_post_uniprot_filter",
                "calculation_id": AOX_POST_UNIPROT_FILTER_ID,
            },
        },
        {
            "artifact_id": "art_target_sequences",
            "relative_path": "formal/calculation/target-sequences.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {
                "operation_id": "op_post_uniprot_filter",
                "calculation_id": AOX_POST_UNIPROT_FILTER_ID,
            },
        },
        {
            "artifact_id": "art_alignment",
            "relative_path": "formal/scoring-alignment.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {
                "operation_id": "op_hmmalign",
                "provider": "hpc_mafft",
                "source_digest": alignment_digest,
            },
        },
        {
            "artifact_id": "art_scores",
            "relative_path": "formal/motif-scores.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_score",
                "contract_id": aox_motif.CONTRACT_ID,
                "input_digest": scoring_result.alignment.input_digest,
            },
        },
        {
            "artifact_id": "art_report",
            "relative_path": "formal/report.md",
            "scope": "formal",
            "origin": "report",
            "kind": "report",
            "provenance": {
                "report_id": "report_aox",
                "draft_id": "draft_aox",
                "content_ref": "doc_report_aox",
                "content_document_digest": report_digest,
                "draft_published": attempt_kind == "positive",
            },
        },
        {
            "artifact_id": "art_candidates",
            "relative_path": "formal/candidates.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {"operation_id": "op_candidate_filter"},
        },
        {
            "artifact_id": "art_membership",
            "relative_path": "formal/cdhit-membership.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_cdhit",
                "schema_id": aox_similarity.MEMBERSHIP_SCHEMA_ID,
            },
        },
        {
            "artifact_id": "art_nodes",
            "relative_path": "formal/graph-nodes.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {"operation_id": "op_similarity"},
        },
        {
            "artifact_id": "art_edges",
            "relative_path": "formal/graph-edges.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {"operation_id": "op_similarity"},
        },
        {
            "artifact_id": "art_graph_manifest",
            "relative_path": "formal/graph-manifest.json",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_similarity",
                "calculation_id": aox_similarity.CALCULATION_ID,
            },
        },
        *probe_fixture["artifacts"],
    ]
    operations = [
        *probe_fixture["operations"],
        _operation(
            "op_ncbi",
            outputs=[("art_ncbi_provider_sequences", ncbi_digest)],
        ),
        _operation(
            "op_hmm_reference_set_selection",
            inputs=[("art_ncbi_provider_sequences", ncbi_digest)],
            outputs=[("art_hmm_reference_set", hmm_reference_set_digest)],
        ),
        _operation(
            "op_scoring_reference_selection",
            inputs=[("art_ncbi_provider_sequences", ncbi_digest)],
            outputs=[("art_scoring_reference", scoring_reference_digest)],
        ),
        _operation(
            "op_ebi_hmmer",
            inputs=[("art_hmm_model", hmm_model_digest)],
            outputs=[
                ("art_ebi_hmmer_response", ebi_hmmer_artifact_digest),
                ("art_hmmer_parsed_hits", parsed_hit_digest),
            ],
        ),
        _operation(
            "op_pre_uniprot_score_filter",
            inputs=[("art_hmmer_parsed_hits", parsed_hit_digest)],
            outputs=[
                (
                    "art_hmmer_score_filtered_accessions",
                    score_filtered_accession_digest,
                )
            ],
        ),
        _operation(
            "op_uniprot",
            inputs=[
                (
                    "art_hmmer_score_filtered_accessions",
                    score_filtered_accession_digest,
                )
            ],
            outputs=[
                ("art_uniprot_candidates", uniprot_digest),
                ("art_uniprot_metadata", uniprot_metadata_digest),
            ],
        ),
        _operation(
            "op_post_uniprot_filter",
            inputs=[
                (
                    "art_hmmer_score_filtered_accessions",
                    score_filtered_accession_digest,
                ),
                ("art_uniprot_candidates", uniprot_digest),
                ("art_uniprot_metadata", uniprot_metadata_digest),
            ],
            outputs=[
                (
                    "art_post_uniprot_filtered_hits",
                    post_uniprot_filtered_digest,
                ),
                ("art_target_sequences", target_sequence_digest),
            ],
        ),
        _operation(
            "op_align",
            inputs=[("art_hmm_reference_set", hmm_reference_set_digest)],
            outputs=[("art_reference_alignment", reference_alignment_digest)],
        ),
        _operation(
            "op_hmmbuild",
            inputs=[("art_reference_alignment", reference_alignment_digest)],
            outputs=[("art_hmm_model", hmm_model_digest)],
        ),
        _operation(
            "op_scoring_input_assembly",
            inputs=[
                ("art_scoring_reference", scoring_reference_digest),
                ("art_target_sequences", target_sequence_digest),
            ],
            outputs=[("art_scoring_input", scoring_input_digest)],
        ),
        _operation(
            "op_hmmalign",
            inputs=[
                ("art_hmm_model", hmm_model_digest),
                ("art_scoring_input", scoring_input_digest),
            ],
            outputs=[("art_alignment", alignment_digest)],
        ),
        _operation(
            "op_score",
            inputs=[("art_alignment", alignment_digest)],
            outputs=[("art_scores", scored_digest)],
        ),
        _operation(
            "op_candidate_filter",
            inputs=[
                ("art_scores", scored_digest),
                ("art_target_sequences", target_sequence_digest),
            ],
            outputs=[("art_candidates", candidate_digest)],
        ),
        _operation(
            "op_cdhit",
            inputs=[("art_candidates", candidate_digest)],
            outputs=[("art_membership", membership_digest)],
        ),
        _operation(
            "op_similarity",
            inputs=[
                ("art_candidates", candidate_digest),
                ("art_membership", membership_digest),
            ],
            outputs=[
                ("art_nodes", nodes_digest),
                ("art_edges", edges_digest),
                ("art_graph_manifest", manifest_digest),
            ],
        ),
    ]
    operation_runtime_receipts = {
        "op_ncbi": (
            "bio.ncbi_fetch_proteins.provider:v1",
            "provider_http",
            "invocation_ncbi",
        ),
        "op_ebi_hmmer": (
            "bio.hmmer_search.provider:v1",
            "provider_http",
            "invocation_ebi_hmmer",
        ),
        "op_uniprot": (
            "bio.uniprot_fetch.provider:v1",
            "provider_http",
            "invocation_uniprot",
        ),
        "op_align": ("bio_tools.mafft.hpc:v1", "hpc", "job_mafft"),
        "op_hmmbuild": ("bio_tools.hmmbuild.hpc:v1", "hpc", "job_hmmbuild"),
        "op_hmmalign": ("bio_tools.hmmalign.hpc:v1", "hpc", "job_hmmalign"),
        "op_cdhit": ("bio_tools.cdhit.hpc:v1", "hpc", "job_cdhit"),
    }
    operation_by_id = {item["operation_id"]: item for item in operations}
    operation_by_id["op_ebi_hmmer"]["parameters"] = {
        "hmm_artifact_id": "art_hmm_model",
        "hmm_artifact_digest": hmm_model_digest,
        "database": "refprot",
    }
    operation_by_id["op_uniprot"]["parameters"] = {
        "accessions": derived_accessions,
        "source_hit_artifact": {
            "artifact_id": "art_hmmer_score_filtered_accessions",
            "content_digest": score_filtered_accession_digest,
        },
    }
    operation_by_id["op_hmm_reference_set_selection"]["parameters"] = {
        "selected_accessions": list(aox_reference.HMM_REFERENCE_ACCESSIONS),
        "identity_replacement": False,
    }
    operation_by_id["op_hmm_reference_set_selection"]["kind"] = (
        aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
    )
    operation_by_id["op_scoring_reference_selection"]["parameters"] = {
        "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
        "identity_replacement": False,
    }
    operation_by_id["op_scoring_reference_selection"]["kind"] = (
        aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
    )
    operation_by_id["op_scoring_input_assembly"]["parameters"] = {
        "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
        "target_count": len(scoring_input_assembly.targets),
    }
    operation_by_id["op_scoring_input_assembly"]["kind"] = (
        aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
    )
    operation_by_id["op_pre_uniprot_score_filter"]["parameters"] = {
        "hmm_score_exclusive_gt": aox_hmmer.SCORE_THRESHOLD_DISPLAY,
    }
    operation_by_id["op_pre_uniprot_score_filter"]["kind"] = aox_hmmer.CONTRACT_ID
    operation_by_id["op_post_uniprot_filter"]["parameters"] = {
        "length_inclusive": [650, 700],
    }
    operation_by_id["op_post_uniprot_filter"]["kind"] = AOX_POST_UNIPROT_FILTER_ID
    for operation in operations:
        if operation["scope"] == "probe":
            _refresh_operation_identity(operation)
            continue
        if operation["operation_id"] in {
            "op_hmm_reference_set_selection",
            "op_scoring_reference_selection",
            "op_scoring_input_assembly",
            "op_pre_uniprot_score_filter",
            "op_post_uniprot_filter",
            "op_score",
            "op_candidate_filter",
            "op_similarity",
        }:
            _refresh_sandbox_calculation_identity(operation)
            continue
        route_policy_id, selected_backend, backend_run_id = (
            operation_runtime_receipts.get(
                operation["operation_id"],
                (
                    "openzyme_pipeline.scientific_calculation:v1",
                    "sandbox_sdk",
                    f"job_{operation['operation_id']}_sandbox",
                ),
            )
        )
        operation.update(
            {
                "route_policy_id": route_policy_id,
                "selected_backend": selected_backend,
                "backend_run_id": backend_run_id,
                "source_snapshot_digest": _digest("aox-pipeline-source"),
            }
        )
        _refresh_operation_identity(
            operation,
            hpc_workspace_label=hpc_workspace_label,
        )
    product_report_record = {
        "report_id": "report_aox",
        "session_id": "sess_aox_live",
        "task_id": "task_report",
        "lane_id": "lane_report",
        "invocation_id": None,
        "run_id": None,
        "artifact_id": None,
        "status": "ready",
        "title": "AOX/HMM report",
        "summary": "Formula-derived AOX motif result",
        "stage_summary": "Research, execution, and reporting completed.",
        "created_at": "2026-07-17T00:00:08+00:00",
        "updated_at": "2026-07-17T00:00:09+00:00",
    }
    published_draft_record = {
        "draft_id": "draft_aox",
        "session_id": "sess_aox_live",
        "task_id": "task_report",
        "owner_agent_id": "agent_reporter_aox",
        "status": "published",
        "title": "AOX/HMM report",
        "summary": "Formula-derived AOX motif result",
        "content_ref": "doc_report_aox",
        "published_report_id": "report_aox",
        "created_at": "2026-07-17T00:00:07+00:00",
        "updated_at": "2026-07-17T00:00:09+00:00",
    }
    content_document_record = {
        "document_id": "doc_report_aox",
        "session_id": "sess_aox_live",
        "invocation_id": None,
        "document_kind": "report_draft_content",
        "payload": {"markdown": report_bytes.decode("utf-8")},
        "created_at": "2026-07-17T00:00:07+00:00",
        "updated_at": "2026-07-17T00:00:07+00:00",
    }
    report_publish_events = [
        {
            "event_id": "event_report_publish_invoked",
            "cursor": 40,
            "event_type": "tool.invoked",
            "payload": {
                "call_id": "call_report_publish",
                "tool_name": "report.publish",
                "task_id": "task_report",
                "lane_id": "lane_report",
                "role": "reporter",
            },
        },
        {
            "event_id": "event_report_draft_updated",
            "cursor": 41,
            "event_type": "report_draft.updated",
            "payload": published_draft_record,
        },
        {
            "event_id": "event_report_generated",
            "cursor": 42,
            "event_type": "report.generated",
            "payload": product_report_record,
        },
        {
            "event_id": "event_report_publish_completed",
            "cursor": 43,
            "event_type": "tool.completed",
            "payload": {
                "call_id": "call_report_publish",
                "tool_name": "report.publish",
                "task_id": "task_report",
                "lane_id": "lane_report",
                "role": "reporter",
                "ok": True,
                "status": "ok",
            },
        },
    ]
    report = {
        "report_id": "report_aox",
        "status": "ready" if attempt_kind == "positive" else "failed_evidence",
        "session_id": "sess_aox_live" if attempt_kind == "positive" else None,
        "task_id": "task_report" if attempt_kind == "positive" else None,
        "lane_id": "lane_report" if attempt_kind == "positive" else None,
        "invocation_id": None,
        "run_id": None,
        "draft_id": "draft_aox" if attempt_kind == "positive" else None,
        "draft_status": "published" if attempt_kind == "positive" else None,
        "published_report_id": ("report_aox" if attempt_kind == "positive" else None),
        "content_ref": "doc_report_aox" if attempt_kind == "positive" else None,
        "content_document_digest": (
            canonical_digest(content_document_record)
            if attempt_kind == "positive"
            else None
        ),
        "content_document_kind": (
            "report_draft_content" if attempt_kind == "positive" else None
        ),
        "content_document_invocation_id": None,
        "owner_agent_id": "agent_reporter_aox" if attempt_kind == "positive" else None,
        "product_artifact_id": None,
        "publication_action": "report.publish" if attempt_kind == "positive" else None,
        "product_report_record": (
            product_report_record if attempt_kind == "positive" else None
        ),
        "published_draft_record": (
            published_draft_record if attempt_kind == "positive" else None
        ),
        "content_document_record": (
            content_document_record if attempt_kind == "positive" else None
        ),
        "publish_events": report_publish_events if attempt_kind == "positive" else [],
        "cutover_eligible": attempt_kind == "positive",
        "content_artifact_id": "art_report",
        "content_digest": report_digest,
        "artifact_ids": [
            "art_alignment",
            "art_pubmed_response",
            "art_ncbi_provider_sequences",
            "art_hmm_reference_set",
            "art_scoring_reference",
            "art_scoring_input",
            "art_ebi_hmmer_response",
            "art_hmmer_parsed_hits",
            "art_hmmer_score_filtered_accessions",
            "art_uniprot_candidates",
            "art_uniprot_metadata",
            "art_post_uniprot_filtered_hits",
            "art_target_sequences",
            "art_scores",
            "art_candidates",
            "art_membership",
            "art_nodes",
            "art_edges",
            "art_graph_manifest",
            "art_report",
        ],
        "source_ref_ids": ["source_pubmed_aox"],
        "claim_source_links": [
            {
                "claim_id": "claim_motif_reproducible",
                "source_ref_ids": ["source_pubmed_aox"],
                "artifact_ids": ["art_scores"],
            }
        ],
    }
    report_artifact = next(
        artifact for artifact in artifacts if artifact["artifact_id"] == "art_report"
    )
    report_artifact["provenance"] = {
        "report_id": "report_aox",
        "draft_id": "draft_aox",
        "content_ref": "doc_report_aox",
        "content_document_digest": canonical_digest(content_document_record),
        "draft_published": attempt_kind == "positive",
    }
    evidence: dict[str, object] = {
        "provider_identities": [
            {
                "provider_record_id": "provider_record_pubmed",
                "provider": "pubmed",
                "status": "completed",
                "canonical_ref_kind": "engine_invocation",
                "invocation_id": "invocation_pubmed",
                "operation_id": None,
                "cache_hit": False,
                "request_digest": pubmed_request_digest,
                "response_digest": pubmed_response_digest,
                "artifact_ids": ["art_pubmed_response"],
                "source_ref_ids": ["source_pubmed_aox"],
                "source_refs": [
                    {
                        "source_ref_id": "source_pubmed_aox",
                        "pmid": "12345678",
                        "task_id": "task_research",
                        "lane_id": "lane_research",
                        "invocation_id": "invocation_pubmed",
                        "evidence_artifact_id": "art_pubmed_response",
                    }
                ],
            },
            {
                "provider_record_id": "provider_record_ncbi",
                "provider": "ncbi",
                "status": "completed",
                "canonical_ref_kind": "controlled_operation",
                "invocation_id": "invocation_ncbi",
                "operation_id": "op_ncbi",
                "cache_hit": False,
                "request_digest": _digest("ncbi-request"),
                "response_digest": ncbi_digest,
                "artifact_ids": ["art_ncbi_provider_sequences"],
                "source_ref_ids": [],
            },
            {
                "provider_record_id": "provider_record_ebi_hmmer",
                "provider": "ebi_hmmer",
                "status": "completed",
                "canonical_ref_kind": "controlled_operation",
                "invocation_id": "invocation_ebi_hmmer",
                "operation_id": "op_ebi_hmmer",
                "cache_hit": False,
                "request_digest": _digest("ebi-hmmer-request"),
                "response_digest": raw_page_digest,
                "artifact_ids": [
                    "art_ebi_hmmer_response",
                    "art_hmmer_parsed_hits",
                ],
                "source_ref_ids": [],
            },
            {
                "provider_record_id": "provider_record_uniprot",
                "provider": "uniprot",
                "status": "completed",
                "canonical_ref_kind": "controlled_operation",
                "invocation_id": "invocation_uniprot",
                "operation_id": "op_uniprot",
                "cache_hit": False,
                "request_digest": _digest("uniprot-request"),
                "response_digest": uniprot_digest,
                "artifact_ids": [
                    "art_uniprot_candidates",
                    "art_uniprot_metadata",
                ],
                "source_ref_ids": [],
            },
        ],
        "engine_invocations": [
            {
                "invocation_id": "invocation_pubmed",
                "engine_name": "research_tool",
                "status": "succeeded",
                "task_id": "task_research",
                "lane_id": "lane_research",
                "input_ref": "invocation_pubmed:input",
                "input_document_digest": _digest("pubmed-input-document"),
                "output_ref": "invocation_pubmed:output",
                "output_document_digest": _digest("pubmed-output-document"),
                "started_at": "2026-07-17T00:00:00+00:00",
                "finished_at": "2026-07-17T00:00:01+00:00",
                "artifact_refs": [
                    {
                        "artifact_id": "art_pubmed_response",
                        "content_digest": pubmed_digest,
                    }
                ],
            }
        ],
        "toolchain_identities": [
            {
                "toolchain_record_id": "toolchain_record_mafft",
                **_toolchain_identity_fields("mafft"),
                "tool": "mafft",
                "operation_id": "op_align",
                "job_id": "job_mafft",
                "status": "completed",
            },
            {
                "toolchain_record_id": "toolchain_record_hmmbuild",
                **_toolchain_identity_fields("hmmbuild"),
                "tool": "hmmbuild",
                "operation_id": "op_hmmbuild",
                "job_id": "job_hmmbuild",
                "status": "completed",
            },
            {
                "toolchain_record_id": "toolchain_record_hmmalign",
                **_toolchain_identity_fields("hmmalign"),
                "tool": "hmmalign",
                "operation_id": "op_hmmalign",
                "job_id": "job_hmmalign",
                "status": "completed",
            },
            {
                "toolchain_record_id": "toolchain_record_cdhit",
                **_toolchain_identity_fields("cd-hit"),
                "tool": "cd-hit",
                "operation_id": "op_cdhit",
                "job_id": "job_cdhit",
                "status": "completed",
            },
        ],
        "known_positive_probe": probe_fixture["probe"],
        "product_path": {
            "entry_message_count": 1,
            "canonical_api_only": True,
            "cache_hit": False,
            "participant_roles": ["researcher", "executor", "reporter"],
            "session_id": "sess_aox_live",
            "entry_message_id": "msg_entry",
            "final_master_response_id": "msg_final",
            "entry_message_digest": _digest("entry-message"),
            "workspace_projection_digest": _digest("workspace-projection"),
            "event_log_digest": _digest("event-log"),
            "public_final_workspace_digest": _digest("public-final-workspace"),
            "public_final_workspace_response_binding": {
                "receipt_sequence": 5,
                "route": "/v3/sessions/sess_aox_live/workspace",
                "response_digest": _digest("public-final-workspace-response"),
                "response_semantic_digest": _digest("public-final-workspace"),
            },
            "public_final_event_stream_digest": _digest("public-final-events"),
            "public_final_event_last_cursor": 12,
            "public_final_event_response_binding": {
                "receipt_sequence": 6,
                "route": (
                    "/v3/sessions/sess_aox_live/events?replay=1&after_cursor=0"
                ),
                "response_digest": _digest("public-final-events-response"),
                "response_semantic_digest": _digest("public-final-events"),
            },
            "public_final_scientific_evidence_digest": _digest(
                "public-final-scientific-evidence"
            ),
            "runtime_config_digest": effective_config_digest,
            "micu_scenario": "aox_blank_world_cutover",
            "micu_model": "micu-live",
            "micu_invocation_ids": ["invocation_micu_master"],
            "task_ids_by_role": {
                "executor": "task_execute",
                "reporter": "task_report",
                "researcher": "task_research",
            },
            "hpc_workspace_binding": {
                "schema_id": "aox_hpc_workspace_binding@1",
                "label": hpc_workspace_label,
                "workspace_ids": sorted(
                    {
                        str(item.get("hpc_workspace_id") or "")
                        for item in operations
                        if item.get("selected_backend") == "hpc"
                    }
                ),
            },
            "public_api_receipts": _public_api_receipts(),
            "launch_receipt": {
                "root_identity": clean_world["root_identity"],
                "hpc_workspace_label": clean_world["hpc_workspace_label"],
                "campaign_attempt_number": 3 if attempt_kind == "fault" else 1,
                "approval_mode": (
                    "chrome-once" if attempt_kind == "fault" else "auto"
                ),
                "browser_approval_receipt": None,
                "browser_observation_receipt": None,
                "public_api_receipt_digest": canonical_digest(_public_api_receipts()),
                "effective_config": effective_config_payload,
                "effective_config_digest": effective_config_digest,
                "sqlite_initialized_fresh": True,
                "artifact_root_bound": True,
                "blob_root_bound": True,
                "sandbox_root_bound": True,
                "sandbox_runtime_identity": {
                    "image_digest": _identity()["image_digest"],
                    "pipeline_sdk_digest": _identity()["sdk_digest"],
                    "runtime_identity_digest": _digest("sandbox-runtime"),
                    "sandbox_protocol_version": "s10",
                },
            },
        },
        "approvals": [
            *probe_fixture["approvals"],
            {
                "approval_id": "approval_hmmbuild",
                "operation_id": "op_hmmbuild",
                "operation_identity_digest": operation_by_id["op_hmmbuild"][
                    "operation_identity_digest"
                ],
                "decision": "approved",
            },
        ],
        "operations": operations,
        "tasks": [
            {
                "task_id": "task_research",
                "role": "researcher",
                "status": "completed",
                "business_exit": "agent_explicit",
                "lane_id": "lane_research",
                "evidence_refs": ["artifact:art_pubmed_response"],
                **_delegation_workflow_receipt(
                    task_id="task_research", role="researcher"
                ),
            },
            {
                "task_id": "task_execute",
                "role": "executor",
                "status": "completed" if attempt_kind == "positive" else "failed",
                "business_exit": "agent_explicit",
                **_delegation_workflow_receipt(
                    task_id="task_execute", role="executor"
                ),
            },
            {
                "task_id": "task_report",
                "role": "reporter",
                "status": "completed" if attempt_kind == "positive" else "failed",
                "business_exit": "agent_explicit",
                **_delegation_workflow_receipt(
                    task_id="task_report", role="reporter"
                ),
            },
        ],
        "artifacts": artifacts,
        "report": report,
        "final_answer": {
            "message_id": "msg_final",
            "content": (
                "AOX/HMM completed with a sealed report."
                if attempt_kind == "positive"
                else "AOX/HMM failed closed at the injected artifact seam."
            ),
        },
        "scientific_checks": (
            {
                "scoring": {
                    "alignment_artifact_id": "art_alignment",
                    "scored_artifact_id": "art_scores",
                    "scoring_contract_id": aox_motif.CONTRACT_ID,
                    "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
                    "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
                    "input_digest": scoring_result.alignment.input_digest,
                },
                "sequence_join": {
                    "score_filtered_artifact_id": (
                        "art_hmmer_score_filtered_accessions"
                    ),
                    "uniprot_fasta_artifact_id": "art_uniprot_candidates",
                    "uniprot_metadata_artifact_id": "art_uniprot_metadata",
                    "filtered_hits_artifact_id": ("art_post_uniprot_filtered_hits"),
                    "target_fasta_artifact_id": "art_target_sequences",
                    "contract_id": aox_sequence_join.CONTRACT_ID,
                    "contract_digest": aox_sequence_join.CONTRACT_DIGEST,
                    "implementation_digest": aox_sequence_join.IMPLEMENTATION_DIGEST,
                    "metadata": sequence_join_result.metadata(),
                },
                "similarity": {
                    "candidate_fasta_artifact_id": "art_candidates",
                    "membership_artifact_id": "art_membership",
                    "nodes_artifact_id": "art_nodes",
                    "edges_artifact_id": "art_edges",
                    "manifest_artifact_id": "art_graph_manifest",
                    "threshold_ppm": 750_000,
                    "empty_result_reason": None,
                    "calculation_id": aox_similarity.CALCULATION_ID,
                    "calculation_digest": aox_similarity.CALCULATION_DIGEST,
                    "implementation_digest": aox_similarity.IMPLEMENTATION_DIGEST,
                    "candidate_fasta_digest": graph.sequences.input_digest,
                    "membership_digest": graph.membership.input_digest,
                },
                "aox_chain": {
                    "literature_provider_record_id": "provider_record_pubmed",
                    "operation_roles": {
                        "ncbi_fetch": "op_ncbi",
                        "hmm_reference_set_selection": (
                            "op_hmm_reference_set_selection"
                        ),
                        "scoring_reference_selection": (
                            "op_scoring_reference_selection"
                        ),
                        "reference_alignment": "op_align",
                        "hmm_build": "op_hmmbuild",
                        "hmmer_search": "op_ebi_hmmer",
                        "pre_uniprot_score_filter": ("op_pre_uniprot_score_filter"),
                        "uniprot_fetch": "op_uniprot",
                        "post_uniprot_filter": "op_post_uniprot_filter",
                        "scoring_input_assembly": "op_scoring_input_assembly",
                        "candidate_alignment": "op_hmmalign",
                        "motif_score": "op_score",
                        "candidate_filter": "op_candidate_filter",
                        "cdhit": "op_cdhit",
                        "similarity": "op_similarity",
                    },
                    "provider_dependencies": [
                        {
                            "upstream_provider_record_id": "provider_record_ebi_hmmer",
                            "downstream_provider_record_id": "provider_record_uniprot",
                            "derivation_id": aox_hmmer.CONTRACT_ID,
                            "upstream_response_artifact_ids": [
                                "art_ebi_hmmer_response"
                            ],
                            "derivation_operation_id": ("op_pre_uniprot_score_filter"),
                            "parsed_hit_artifact_id": "art_hmmer_parsed_hits",
                            "parsed_hit_artifact_digest": parsed_hit_digest,
                            "derived_accession_artifact_id": (
                                "art_hmmer_score_filtered_accessions"
                            ),
                            "derived_accession_artifact_digest": (
                                score_filtered_accession_digest
                            ),
                            "derivation_contract_digest": (aox_hmmer.CONTRACT_DIGEST),
                            "derivation_implementation_digest": (
                                aox_hmmer.IMPLEMENTATION_DIGEST
                            ),
                            "derived_accessions": derived_accessions,
                            "derived_accessions_digest": canonical_digest(
                                sorted(derived_accessions)
                            ),
                        }
                    ],
                    "artifact_roles": {
                        "literature_evidence": "art_pubmed_response",
                        "ncbi_provider_sequences": "art_ncbi_provider_sequences",
                        "hmm_reference_set": "art_hmm_reference_set",
                        "scoring_reference": "art_scoring_reference",
                        "scoring_input": "art_scoring_input",
                        "reference_alignment": "art_reference_alignment",
                        "hmm_model": "art_hmm_model",
                        "hmmer_response": "art_ebi_hmmer_response",
                        "hmmer_parsed_hits": "art_hmmer_parsed_hits",
                        "hmmer_score_filtered_accessions": (
                            "art_hmmer_score_filtered_accessions"
                        ),
                        "uniprot_sequences": "art_uniprot_candidates",
                        "uniprot_metadata": "art_uniprot_metadata",
                        "post_uniprot_filtered_hits": (
                            "art_post_uniprot_filtered_hits"
                        ),
                        "target_sequences": "art_target_sequences",
                        "scoring_alignment": "art_alignment",
                        "motif_scores": "art_scores",
                        "candidates": "art_candidates",
                        "cdhit_membership": "art_membership",
                        "graph_nodes": "art_nodes",
                        "graph_edges": "art_edges",
                        "graph_manifest": "art_graph_manifest",
                    },
                    "excluded_scoring_sequence_ids": [aox_motif.REFERENCE_ACCESSION],
                },
            }
            if attempt_kind == "positive"
            else {}
        ),
        "warnings": [],
        "degradations": [],
        "scientific_outcome": {
            "status": "discovered" if attempt_kind == "positive" else "failed",
            "candidate_count": len(candidate_ids) if attempt_kind == "positive" else 0,
            "cutover_eligible": attempt_kind == "positive",
        },
        "fault_injection": (
            None
            if attempt_kind == "positive"
            else {
                "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
                "target_operation_id": "op_score",
                "reached_target_seam": True,
                "expected_failure_observed": True,
                "terminal_failure_operation_id": "op_score",
            }
        ),
    }
    if scientific_branch == "hmmer_upstream_empty":
        if attempt_kind != "positive":
            raise ValueError(
                "healthy-empty fixture is only valid for positive attempts"
            )
        _apply_hmmer_upstream_empty_fixture(artifact_root, evidence)
    elif scientific_branch != "nonempty":
        raise ValueError(f"unknown scientific fixture branch: {scientific_branch}")
    namespaced = _namespace_evidence(evidence, run_suffix=run_suffix)
    if attempt_kind == "positive":
        _attach_product_receipts(
            artifact_root,
            namespaced,
            run_suffix=run_suffix,
        )
    else:
        _apply_derived_reference_fault_fixture(
            artifact_root,
            namespaced,
            run_suffix=run_suffix,
        )
    _attach_public_final_snapshot_fixture(artifact_root, namespaced)
    return namespaced


def _namespace_evidence(
    evidence: dict[str, object],
    *,
    run_suffix: str | None,
) -> dict[str, object]:
    if not run_suffix:
        return evidence
    identity_prefixes = (
        "approval_",
        "art_",
        "call_",
        "check_",
        "claim_",
        "doc_",
        "draft_",
        "event_",
        "invocation_",
        "job_",
        "lane_",
        "msg_",
        "op_",
        "probe_",
        "provider_record_",
        "report_",
        "sess_",
        "source_",
        "task_",
        "toolchain_record_",
    )

    semantic_text_keys = {
        "business_exit",
        "canonical_ref_kind",
        "content_document_kind",
        "document_kind",
        "event_type",
        "kind",
        "operation_identity_schema",
        "publication_action",
        "role",
        "schema_id",
        "schema_version",
        "status",
        "tool_name",
    }

    def visit(value, *, field_name: str | None = None):
        if isinstance(value, dict):
            return {key: visit(item, field_name=key) for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item, field_name=field_name) for item in value]
        if isinstance(value, str) and field_name == "evidence_refs":
            kind, separator, record_id = value.partition(":")
            if separator and record_id.startswith(identity_prefixes):
                return f"{kind}:{record_id}_{run_suffix}"
        if (
            isinstance(value, str)
            and field_name not in semantic_text_keys
            and value.startswith(identity_prefixes)
        ):
            return f"{value}_{run_suffix}"
        return value

    namespaced = visit(evidence)
    report = namespaced["report"]
    content_document = report.get("content_document_record")
    if isinstance(content_document, dict):
        content_document_digest = canonical_digest(content_document)
        report["content_document_digest"] = content_document_digest
        report_artifact_id = report["content_artifact_id"]
        report_artifact = next(
            artifact
            for artifact in namespaced["artifacts"]
            if artifact["artifact_id"] == report_artifact_id
        )
        report_artifact["provenance"]["content_document_digest"] = (
            content_document_digest
        )
    operation_identities = {}
    for operation in namespaced["operations"]:
        if operation.get("canonical_ref_kind") == "sandbox_calculation":
            _refresh_sandbox_calculation_identity(operation)
        else:
            _refresh_operation_identity(operation)
        operation_identities[operation["operation_id"]] = operation[
            "operation_identity_digest"
        ]
    for approval in namespaced["approvals"]:
        approval["operation_identity_digest"] = operation_identities[
            approval["operation_id"]
        ]
    for task in namespaced["tasks"]:
        task["delegation_request_digest"] = canonical_digest(
            task["delegation_request"]
        )
    product_path = namespaced["product_path"]
    public_api_receipts = _public_api_receipts(product_path["session_id"])
    product_path["public_api_receipts"] = public_api_receipts
    product_path["launch_receipt"]["public_api_receipt_digest"] = canonical_digest(
        public_api_receipts
    )
    return namespaced


def _attach_public_final_snapshot_fixture(
    artifact_root: Path,
    evidence: dict[str, object],
) -> None:
    product_path = evidence["product_path"]
    session_id = str(product_path["session_id"])
    fault = evidence.get("fault_injection")
    closure: dict[str, object] = {}
    if isinstance(fault, dict):
        closure_artifact_id = str(fault["negative_state_closure_artifact_id"])
        closure_artifact = next(
            item
            for item in evidence["artifacts"]
            if item["artifact_id"] == closure_artifact_id
        )
        closure_document = json.loads(
            (artifact_root / closure_artifact["relative_path"]).read_text(
                encoding="utf-8"
            )
        )
        closure = dict(closure_document["negative_state_closure"])
    task_items = [
        {
            "task_id": item.get("task_id"),
            "kind": item.get("kind"),
            "status": item.get("status"),
            "assigned_ref": item.get("assigned_ref"),
            "lane_id": item.get("lane_id"),
        }
        for item in (closure.get("task_receipts") or evidence.get("tasks") or [])
    ]
    if closure:
        report_states = [dict(item) for item in closure.get("report_states") or []]
        draft_states = [dict(item) for item in closure.get("draft_states") or []]
        final_content = str(evidence["final_answer"]["content"])
        conversation = [
            {
                "message_id": str(product_path["entry_message_id"]),
                "role": "user",
                "content": "entry-message",
            },
            {
                "message_id": str(evidence["final_answer"]["message_id"]),
                "role": "assistant",
                "content": final_content,
            },
        ]
        events = [
            {
                "event_id": item["event_id"],
                "session_id": session_id,
                "event_type": item["event_type"],
                "schema_version": "openzyme.v3.event.v1",
                "visibility": "public",
                "actor_ref": item.get("actor_ref"),
                "command_id": item.get("command_id"),
                "created_at": "2026-07-17T00:00:20+00:00",
                "cursor": item["cursor"],
                "payload": {
                    "operation_id": fault["terminal_failure_operation_id"],
                    "failure_code": "artifact_blob_digest_mismatch",
                },
            }
            for item in closure.get("durable_event_receipts") or []
        ]
    else:
        report = dict(evidence.get("report") or {})
        report_states = [
            {
                "report_id": report.get("report_id"),
                "task_id": report.get("task_id"),
                "status": report.get("status"),
                "artifact_id": report.get("content_artifact_id"),
            }
        ]
        draft_states = []
        conversation = [
            {
                "message_id": str(product_path["entry_message_id"]),
                "role": "user",
                "content": "entry-message",
            },
            {
                "message_id": str(evidence["final_answer"]["message_id"]),
                "role": "assistant",
                "content": str(evidence["final_answer"]["content"]),
            },
        ]
        events = [
            {
                "event_id": "event_public_final_positive",
                "session_id": session_id,
                "event_type": "task.completed",
                "schema_version": "openzyme.v3.event.v1",
                "visibility": "public",
                "actor_ref": "agent_reporter_aox",
                "command_id": None,
                "created_at": "2026-07-17T00:00:20+00:00",
                "cursor": 1,
                "payload": {"task_id": product_path["task_ids_by_role"]["reporter"]},
            }
        ]
    scientific_operations = [
        {
            "operation_id": item.get("operation_id"),
            "task_id": item.get("task_id"),
            "sdk_module": dict(item.get("operation_identity_material") or {}).get(
                "sdk_module"
            ),
            "function_name": dict(item.get("operation_identity_material") or {}).get(
                "function_name"
            ),
            "selected_backend": item.get("selected_backend"),
            "status": item.get("status"),
            "error_code": item.get("failure_code"),
            "operation_digest": item.get("operation_identity_digest"),
            "input_artifact_ids": [
                ref.get("artifact_id")
                for ref in item.get("inputs") or []
                if isinstance(ref, dict)
            ],
        }
        for item in evidence.get("operations") or []
        if item.get("scope") == "formal"
    ]
    workspace = {
        "session": {"session_id": session_id},
        "conversation": conversation,
        "task_board": {"items": task_items},
        "pending_approvals": [],
        "report_drafts": draft_states,
        "reports": report_states,
        "scientific_evidence": {"operations": scientific_operations},
    }
    workspace_digest = canonical_digest(workspace)
    event_digest = canonical_digest(events)
    receipts = product_path["public_api_receipts"]
    workspace_receipt = next(
        item
        for item in reversed(receipts)
        if item["method"] == "GET"
        and item["route"] == f"/v3/sessions/{session_id}/workspace"
    )
    event_receipt = next(
        item
        for item in reversed(receipts)
        if item["method"] == "GET" and "/events?replay=1&after_cursor=0" in item["route"]
    )
    workspace_receipt["response_semantic_digest"] = workspace_digest
    event_receipt["response_semantic_digest"] = event_digest
    workspace_binding = {
        "receipt_sequence": workspace_receipt["sequence"],
        "route": workspace_receipt["route"],
        "response_digest": workspace_receipt["response_digest"],
        "response_semantic_digest": workspace_digest,
    }
    event_binding = {
        "receipt_sequence": event_receipt["sequence"],
        "route": event_receipt["route"],
        "response_digest": event_receipt["response_digest"],
        "response_semantic_digest": event_digest,
    }
    workspace_record = {
        "schema_id": "aox_public_final_workspace_snapshot@1",
        "session_id": session_id,
        "workspace": workspace,
        "workspace_digest": workspace_digest,
        "response_binding": workspace_binding,
    }
    event_record = {
        "schema_id": "aox_public_final_event_replay@1",
        "session_id": session_id,
        "replay": True,
        "after_cursor": 0,
        "events": events,
        "event_count": len(events),
        "last_cursor": max(item["cursor"] for item in events),
        "event_stream_digest": event_digest,
        "response_binding": event_binding,
    }
    workspace_bytes = canonical_json_bytes(workspace_record) + b"\n"
    event_bytes = canonical_json_bytes(event_record) + b"\n"
    workspace_id = f"art_public_final_workspace_{session_id}"
    event_id = f"art_public_final_events_{session_id}"
    workspace_path = "formal/attestation/public-final-workspace.json"
    event_path = "formal/attestation/public-final-event-replay.json"
    _write_artifact(artifact_root, workspace_path, workspace_bytes)
    _write_artifact(artifact_root, event_path, event_bytes)
    evidence["artifacts"].extend(
        [
            {
                "artifact_id": workspace_id,
                "relative_path": workspace_path,
                "scope": "formal",
                "origin": "attestation",
                "kind": "workspace_projection",
                "provenance": {
                    "producer": "aox_public_final_workspace_snapshot@1"
                },
            },
            {
                "artifact_id": event_id,
                "relative_path": event_path,
                "scope": "formal",
                "origin": "attestation",
                "kind": "event_log",
                "provenance": {"producer": "aox_public_final_event_replay@1"},
            },
        ]
    )
    product_path.update(
        {
            "public_final_workspace_digest": workspace_digest,
            "public_final_workspace_response_binding": workspace_binding,
            "public_final_event_stream_digest": event_digest,
            "public_final_event_last_cursor": event_record["last_cursor"],
            "public_final_event_response_binding": event_binding,
            "public_final_scientific_evidence_digest": canonical_digest(
                workspace["scientific_evidence"]
            ),
            "public_final_workspace_artifact_id": workspace_id,
            "public_final_workspace_artifact_digest": _digest_bytes(workspace_bytes),
            "public_final_event_replay_artifact_id": event_id,
            "public_final_event_replay_artifact_digest": _digest_bytes(event_bytes),
        }
    )
    product_path["launch_receipt"]["public_api_receipt_digest"] = canonical_digest(
        receipts
    )


def _apply_derived_reference_fault_fixture(
    artifact_root: Path,
    evidence: dict[str, object],
    *,
    run_suffix: str | None,
) -> None:
    def scoped_id(value: str) -> str:
        return value if not run_suffix else f"{value}_{run_suffix}"

    source_artifact_id = scoped_id("art_ncbi_provider_sequences")
    target_artifact_id = scoped_id("art_hmm_reference_set")
    closure_artifact_id = scoped_id("art_fault_negative_state_closure")
    source_operation_id = scoped_id("op_ncbi")
    derivation_operation_id = scoped_id("op_hmm_reference_set_selection")
    consumer_operation_id = scoped_id("op_align")
    research_task_id = scoped_id("task_research")
    execution_task_id = scoped_id("task_execute")
    reporting_task_id = scoped_id("task_report")
    session_id = scoped_id("sess_aox_live")
    final_message_id = scoped_id("msg_final")

    artifacts = [dict(item) for item in evidence["artifacts"]]
    artifact_by_id = {str(item["artifact_id"]): item for item in artifacts}
    source_artifact = artifact_by_id[source_artifact_id]
    target_artifact = artifact_by_id[target_artifact_id]
    source_content = (
        artifact_root / str(source_artifact["relative_path"])
    ).read_bytes()
    source_digest = _digest_bytes(source_content)
    derived = aox_reference.select_hmm_reference_set(
        source_content,
        expected_contract_id=aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
        expected_contract_digest=(
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        ),
        expected_implementation_digest=(
            aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        ),
        expected_input_digest=source_digest,
    )
    expected_target_content = derived.to_fasta().encode("utf-8")
    target_path = artifact_root / str(target_artifact["relative_path"])
    assert target_path.read_bytes() == expected_target_content
    fault = inject_artifact_byte_flip(
        artifact_root,
        relative_path=str(target_artifact["relative_path"]),
        byte_offset=4,
    )

    operations = [dict(item) for item in evidence["operations"]]
    operation_by_id = {str(item["operation_id"]): item for item in operations}
    source_operation = operation_by_id[source_operation_id]
    derivation_operation = operation_by_id[derivation_operation_id]
    consumer_operation = operation_by_id[consumer_operation_id]
    source_operation["task_id"] = research_task_id
    source_operation["lane_id"] = scoped_id("lane_research")
    source_operation["parameters"] = {
        "accessions": list(aox_reference.NCBI_REFERENCE_ACCESSIONS),
        "fields": ["definition", "organism", "length"],
        "output_dir": "/workspace/output/bio/ncbi",
    }
    source_operation["outputs"] = [
        {"artifact_id": source_artifact_id, "content_digest": source_digest}
    ]
    _refresh_operation_identity(source_operation)
    derivation_operation["task_id"] = execution_task_id
    derivation_operation["lane_id"] = scoped_id("lane_execute")
    derivation_operation["inputs"] = [
        {"artifact_id": source_artifact_id, "content_digest": source_digest}
    ]
    derivation_operation["outputs"] = [
        {
            "artifact_id": target_artifact_id,
            "content_digest": fault["before_digest"],
        }
    ]
    _refresh_sandbox_calculation_identity(derivation_operation)
    consumer_operation.update(
        {
            "task_id": execution_task_id,
            "lane_id": scoped_id("lane_execute"),
            "status": "failed",
            "terminal": True,
            "failure_code": "artifact_blob_digest_mismatch",
            "inputs": [
                {
                    "artifact_id": target_artifact_id,
                    "content_digest": fault["before_digest"],
                }
            ],
            "outputs": [],
            "route_policy_id": "bio_tools.mafft.hpc:v1",
            "selected_backend": "hpc",
            "backend_run_id": scoped_id("job_mafft_fault"),
            "source_snapshot_digest": _digest("aox-pipeline-source"),
        }
    )
    _refresh_operation_identity(consumer_operation)
    evidence["operations"] = [
        item for item in operations if item.get("scope") == "probe"
    ] + [source_operation, derivation_operation, consumer_operation]

    probe_approvals = [
        dict(item)
        for item in evidence["approvals"]
        if str(item.get("operation_id") or "").startswith("op_probe_")
    ]
    evidence["approvals"] = [
        *probe_approvals,
        {
            "approval_id": scoped_id("approval_fault_ncbi"),
            "operation_id": source_operation_id,
            "operation_identity_digest": source_operation["operation_identity_digest"],
            "decision": "approved",
        },
        {
            "approval_id": scoped_id("approval_fault_mafft"),
            "operation_id": consumer_operation_id,
            "operation_identity_digest": consumer_operation[
                "operation_identity_digest"
            ],
            "decision": "approved",
        },
    ]
    evidence["provider_identities"] = [
        item
        for item in evidence["provider_identities"]
        if item.get("provider") == "ncbi"
    ]
    ncbi_provider = evidence["provider_identities"][0]
    ncbi_provider.update(
        {
            "operation_id": source_operation_id,
            "artifact_ids": [source_artifact_id],
            "invocation_id": source_operation["backend_run_id"],
            "request_digest": source_operation["params_digest"],
            "response_digest": source_digest,
        }
    )
    evidence["engine_invocations"] = []
    evidence["toolchain_identities"] = []

    source_artifact["provenance"] = {
        "operation_id": source_operation_id,
        "provider": "ncbi",
    }
    target_artifact["provenance"] = {
        "operation_id": derivation_operation_id,
        "calculation_id": aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
        "controlled_fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
        "catalog_relative_path": "aox_hmm/AOX_ref21.fasta",
    }
    kept_formal_artifact_ids = {source_artifact_id, target_artifact_id}
    for artifact in artifacts:
        if (
            artifact.get("scope") == "formal"
            and artifact.get("artifact_id") not in kept_formal_artifact_ids
        ):
            stale_path = artifact_root / str(artifact["relative_path"])
            if stale_path.is_file():
                stale_path.unlink()
    evidence["artifacts"] = [
        item for item in artifacts if item.get("scope") == "probe"
    ] + [source_artifact, target_artifact]

    task_specs = (
        (
            research_task_id,
            "researcher",
            "research",
            "completed",
            "agent_researcher_aox",
            scoped_id("lane_research"),
            [source_artifact_id],
        ),
        (
            execution_task_id,
            "executor",
            "execution",
            "failed",
            "agent_executor_aox",
            scoped_id("lane_execute"),
            [consumer_operation_id, target_artifact_id],
        ),
        (
            reporting_task_id,
            "reporter",
            "reporting",
            "blocked",
            "agent_reporter_aox",
            scoped_id("lane_report"),
            [consumer_operation_id],
        ),
    )
    task_records: list[dict[str, object]] = []
    for task_id, role, kind, status, assigned_ref, lane_id, evidence_refs in task_specs:
        finish_payload = {
            "task_id": task_id,
            "status": status,
            "finished_by": assigned_ref,
            "evidence_refs": evidence_refs,
        }
        task_records.append(
            {
                "task_id": task_id,
                "role": role,
                "kind": kind,
                "status": status,
                "business_exit": "agent_explicit",
                "assigned_ref": assigned_ref,
                "lane_id": lane_id,
                "finish_ref": scoped_id(f"doc_finish_{role}"),
                "finish_payload_digest": canonical_digest(finish_payload),
                "finished_by": assigned_ref,
                "evidence_refs": evidence_refs,
                **_delegation_workflow_receipt(task_id=task_id, role=role),
            }
        )
    evidence["tasks"] = sorted(task_records, key=lambda item: str(item["task_id"]))

    final_content = (
        "AOX/HMM failed closed at the injected reference-set artifact seam: "
        "failure_code=artifact_blob_digest_mismatch status=failed."
    )
    evidence["final_answer"] = {
        "message_id": final_message_id,
        "content": final_content,
    }
    consumer_identity = dict(consumer_operation["operation_identity_material"])
    consumer_runner_contract_expectation = {
        "tool_id": "bio_tools.mafft",
        **dict(
            evidence["product_path"]["launch_receipt"]["effective_config"]["execution"][
                "aox_runner_contract_expectations"
            ]["contracts"]["bio_tools.mafft"]
        ),
    }
    negative_closure = {
        "schema_id": "aox_fault_negative_state_closure@1",
        "session_id": session_id,
        "target_artifact_id": target_artifact_id,
        "terminal_failure_operation_id": consumer_operation_id,
        "task_receipts": evidence["tasks"],
        "report_states": [],
        "draft_states": [],
        "conversation_receipts": [
            {
                "message_id": scoped_id("msg_entry"),
                "role": "user",
                "content_digest": _digest("entry-message"),
            },
            {
                "message_id": final_message_id,
                "role": "assistant",
                "content_digest": _digest_bytes(final_content.encode("utf-8")),
            },
        ],
        "success_claim_message_ids": [],
        "final_assistant_failure_message_id": final_message_id,
        "final_assistant_failure_code": "artifact_blob_digest_mismatch",
        "final_assistant_failure_status": "failed",
        "consumer_runner_contract_expectation": (consumer_runner_contract_expectation),
        "durable_event_receipts": [
            {
                "event_id": scoped_id("event_fault_terminal"),
                "cursor": 1,
                "event_type": "controlled_operation.failed",
                "actor_ref": "agent_executor_aox",
                "command_id": scoped_id("call_fault_mafft"),
                "payload_digest": canonical_digest(
                    {
                        "operation_id": consumer_operation_id,
                        "failure_code": "artifact_blob_digest_mismatch",
                    }
                ),
            }
        ],
        "consumer_states": [
            {
                "operation_id": consumer_operation_id,
                "task_id": execution_task_id,
                "sdk_module": consumer_identity["sdk_module"],
                "function_name": consumer_identity["function_name"],
                "selected_backend": consumer_operation["selected_backend"],
                "status": consumer_operation["status"],
                "failure_code": consumer_operation["failure_code"],
                "operation_identity_digest": consumer_operation[
                    "operation_identity_digest"
                ],
            }
        ],
        "successful_alternate_consumer_ids": [],
        "observed_prefault_deliverable_paths": ["aox_hmm/AOX_ref21.fasta"],
        "post_fault_final_deliverable_paths": [],
        "complete_final_deliverable_set_present": False,
    }
    closure_payload = {
        "schema_id": "aox_blank_world_live_blocker@1",
        "attempt_kind": "fault",
        "failure_code": "artifact_blob_digest_mismatch",
        "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
        "target_artifact_id": target_artifact_id,
        "source_artifact_id": source_artifact_id,
        "source_operation_id": source_operation_id,
        "derivation_operation_id": derivation_operation_id,
        "derivation_id": aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
        "terminal_failure_operation_id": consumer_operation_id,
        "negative_state_closure": negative_closure,
    }
    closure_relative_path = "formal/fault/negative-state-closure.json"
    closure_content = canonical_json_bytes(closure_payload) + b"\n"
    closure_digest = _write_artifact(
        artifact_root,
        closure_relative_path,
        closure_content,
    )
    closure_artifact = {
        "artifact_id": closure_artifact_id,
        "relative_path": closure_relative_path,
        "scope": "formal",
        "origin": "report",
        "kind": "failure_evidence",
        "provenance": {
            "producer": "aox_fault_negative_state_closure@1",
            "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
        },
    }
    evidence["artifacts"].append(closure_artifact)
    evidence["report"] = {
        "report_id": scoped_id("report_fault_closure"),
        "status": "failed_evidence",
        "cutover_eligible": False,
        "content_artifact_id": closure_artifact_id,
        "content_digest": closure_digest,
        "artifact_ids": [closure_artifact_id, target_artifact_id],
        "source_ref_ids": [],
        "claim_source_links": [],
    }
    evidence["scientific_checks"] = {}
    evidence["warnings"] = []
    evidence["degradations"] = ["controlled_fault_injection"]
    evidence["scientific_outcome"] = {
        "status": "failed",
        "failure_code": "artifact_blob_digest_mismatch",
        "cutover_eligible": False,
    }
    evidence["fault_injection"] = {
        **fault,
        "target_artifact_id": target_artifact_id,
        "source_artifact_id": source_artifact_id,
        "source_artifact_digest": source_digest,
        "source_operation_id": source_operation_id,
        "derivation_operation_id": derivation_operation_id,
        "derivation_id": aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
        "derivation_contract_digest": (
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        ),
        "derivation_implementation_digest": (
            aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        ),
        "consumer_tool_id": "bio_tools.mafft",
        "consumer_runner_contract_expectation": (consumer_runner_contract_expectation),
        "terminal_failure_operation_id": consumer_operation_id,
        "failure_code": "artifact_blob_digest_mismatch",
        "negative_state_closure_artifact_id": closure_artifact_id,
        "negative_state_closure_digest": closure_digest,
        "reached_target_seam": True,
        "expected_failure_observed": True,
    }


def _attach_product_receipts(
    artifact_root: Path,
    evidence: dict[str, object],
    *,
    run_suffix: str | None,
) -> None:
    suffix = "" if not run_suffix else f"_{run_suffix}"
    workspace_artifact_id = f"art_workspace_projection{suffix}"
    event_artifact_id = f"art_event_log{suffix}"
    product_path = evidence["product_path"]
    report = evidence["report"]
    operations = evidence["operations"]
    providers = evidence["provider_identities"]
    toolchains = evidence["toolchain_identities"]
    approvals = evidence["approvals"]
    tasks = evidence["tasks"]
    final_answer = evidence["final_answer"]
    outcome = evidence["scientific_outcome"]
    workspace_payload = {
        "schema_id": "aox_workspace_projection_receipt@1",
        "session_id": product_path["session_id"],
        "task_ids_by_role": product_path["task_ids_by_role"],
        "operation_ids": sorted(item["operation_id"] for item in operations),
        "provider_invocation_ids": sorted(
            str(item.get("invocation_id") or "") for item in providers
        ),
        "toolchain_job_ids": sorted(item["job_id"] for item in toolchains),
        "report_id": report["report_id"],
        "final_master_response_id": product_path["final_master_response_id"],
        "root_identity": product_path["launch_receipt"]["root_identity"],
        "runtime_config_digest": product_path["runtime_config_digest"],
        "cache_hit": product_path["cache_hit"],
        "participant_roles": sorted(product_path["participant_roles"]),
        "task_receipts": sorted(
            (
                {
                    "task_id": item["task_id"],
                    "role": item["role"],
                    "status": item["status"],
                    "business_exit": item["business_exit"],
                }
                for item in tasks
            ),
            key=lambda item: item["task_id"],
        ),
        "report_receipt": {
            "report_id": report["report_id"],
            "session_id": report["session_id"],
            "task_id": report["task_id"],
            "lane_id": report["lane_id"],
            "status": report["status"],
            "invocation_id": report["invocation_id"],
            "run_id": report["run_id"],
            "product_artifact_id": report["product_artifact_id"],
            "draft_id": report["draft_id"],
            "draft_status": report["draft_status"],
            "published_report_id": report["published_report_id"],
            "owner_agent_id": report["owner_agent_id"],
            "content_ref": report["content_ref"],
            "content_document_kind": report["content_document_kind"],
            "content_document_invocation_id": report["content_document_invocation_id"],
            "content_document_digest": report["content_document_digest"],
            "publication_action": report["publication_action"],
            "content_artifact_id": report["content_artifact_id"],
            "content_digest": report["content_digest"],
        },
        "final_answer_receipt": {
            "message_id": final_answer["message_id"],
            "content_digest": _digest_bytes(final_answer["content"].encode("utf-8")),
        },
        "scientific_outcome": {
            "status": outcome["status"],
            "candidate_count": outcome["candidate_count"],
            "empty_result_reason": outcome.get("empty_result_reason"),
            "cutover_eligible": outcome["cutover_eligible"],
        },
        "micu_scenario": product_path["micu_scenario"],
        "micu_model": product_path["micu_model"],
        "micu_invocation_ids": sorted(product_path["micu_invocation_ids"]),
    }
    event_payload = {
        "schema_id": "aox_event_log_receipt@1",
        "session_id": product_path["session_id"],
        "entry_message_id": product_path["entry_message_id"],
        "entry_message_digest": product_path["entry_message_digest"],
        "final_master_response_id": product_path["final_master_response_id"],
        "task_ids": sorted(product_path["task_ids_by_role"].values()),
        "operation_ids": sorted(item["operation_id"] for item in operations),
        "approval_bindings": sorted(
            (
                {
                    "approval_id": item["approval_id"],
                    "operation_id": item["operation_id"],
                    "operation_identity_digest": item["operation_identity_digest"],
                }
                for item in approvals
            ),
            key=lambda item: item["approval_id"],
        ),
        "micu_invocation_ids": sorted(product_path["micu_invocation_ids"]),
        "task_finishes": sorted(
            (
                {
                    "task_id": item["task_id"],
                    "status": item["status"],
                    "business_exit": item["business_exit"],
                }
                for item in tasks
            ),
            key=lambda item: item["task_id"],
        ),
        "operation_finishes": sorted(
            (
                {
                    "operation_id": item["operation_id"],
                    "operation_identity_digest": item["operation_identity_digest"],
                    "status": item["status"],
                    "terminal": item["terminal"],
                }
                for item in operations
            ),
            key=lambda item: item["operation_id"],
        ),
        "provider_invocations": sorted(
            (
                {
                    "invocation_id": item["invocation_id"],
                    "operation_id": item["operation_id"],
                    "provider": item["provider"],
                    "status": item["status"],
                }
                for item in providers
            ),
            key=lambda item: str(item["invocation_id"] or ""),
        ),
        "toolchain_jobs": sorted(
            (
                {
                    "job_id": item["job_id"],
                    "operation_id": item["operation_id"],
                    "tool": item["tool"],
                    "status": item["status"],
                }
                for item in toolchains
            ),
            key=lambda item: item["job_id"],
        ),
        "report_publish": {
            "report_id": report["report_id"],
            "session_id": report["session_id"],
            "task_id": report["task_id"],
            "lane_id": report["lane_id"],
            "status": report["status"],
            "invocation_id": report["invocation_id"],
            "run_id": report["run_id"],
            "product_artifact_id": report["product_artifact_id"],
            "draft_id": report["draft_id"],
            "draft_status": report["draft_status"],
            "published_report_id": report["published_report_id"],
            "owner_agent_id": report["owner_agent_id"],
            "content_ref": report["content_ref"],
            "content_document_kind": report["content_document_kind"],
            "content_document_invocation_id": report["content_document_invocation_id"],
            "content_document_digest": report["content_document_digest"],
            "publication_action": report["publication_action"],
            "content_digest": report["content_digest"],
            "publish_events": report["publish_events"],
        },
        "browser_approval_events": [],
        "browser_approval_event_stream_digest": canonical_digest([]),
    }
    workspace_bytes = canonical_json_bytes(workspace_payload) + b"\n"
    event_bytes = canonical_json_bytes(event_payload) + b"\n"
    workspace_digest = _write_artifact(
        artifact_root,
        "formal/attestation/workspace-projection.json",
        workspace_bytes,
    )
    event_digest = _write_artifact(
        artifact_root,
        "formal/attestation/event-log.json",
        event_bytes,
    )
    evidence["artifacts"].extend(
        [
            {
                "artifact_id": workspace_artifact_id,
                "relative_path": "formal/attestation/workspace-projection.json",
                "scope": "formal",
                "origin": "attestation",
                "kind": "workspace_projection",
                "provenance": {"producer": "host_workspace_projection"},
            },
            {
                "artifact_id": event_artifact_id,
                "relative_path": "formal/attestation/event-log.json",
                "scope": "formal",
                "origin": "attestation",
                "kind": "event_log",
                "provenance": {"producer": "host_event_log_projection"},
            },
        ]
    )
    product_path["workspace_projection_artifact_id"] = workspace_artifact_id
    product_path["workspace_projection_digest"] = workspace_digest
    product_path["event_log_artifact_id"] = event_artifact_id
    product_path["event_log_digest"] = event_digest
    product_path["browser_approval_event_stream_digest"] = canonical_digest([])


def _build_bundle(
    tmp_path: Path,
    *,
    attempt_kind: str = "positive",
    scientific_branch: str = "nonempty",
    mutate_evidence=None,
    ledger_before: dict[str, object] | None = None,
    ledger_after: dict[str, object] | None = None,
) -> tuple[dict[str, object], Path, Path]:
    effective_config = _effective_config()
    if attempt_kind == "fault":
        effective_config["driver"]["approval_mode"] = "chrome-once"
        effective_config["driver"]["ui_dist_digest"] = _digest("ui-dist")
    identity = _identity()
    identity["config_digest"] = canonical_digest(effective_config)
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind=attempt_kind,
        attempt_id=f"{attempt_kind}-one",
        allowed_prerequisites=_allowed_prerequisites(identity),
    )
    evidence = _valid_evidence(
        roots.artifact_root,
        attempt_kind=attempt_kind,
        clean_world=roots.proof,
        scientific_branch=scientific_branch,
        effective_config=effective_config,
    )
    if mutate_evidence is not None:
        mutate_evidence(evidence)
    payload = build_attempt_bundle(
        attempt_id=roots.attempt_id,
        attempt_kind=attempt_kind,
        identity=identity,
        clean_world=roots.proof,
        ledger_before=ledger_before or _ledger_snapshot(),
        ledger_after=ledger_after
        or _ledger_snapshot(charged_tokens=20, attempt_count=2),
        artifact_root=roots.artifact_root,
        evidence=evidence,
        sealed_at="2026-07-17T00:00:00+00:00",
    )
    bundle_path = roots.evidence_root / "attempt-bundle.json"
    seal_attempt_bundle(payload, bundle_path)
    return payload, bundle_path, roots.artifact_root


def _rewrite_envelope(bundle_path: Path, mutate) -> None:
    envelope = json.loads(bundle_path.read_text(encoding="utf-8"))
    mutate(envelope)
    bundle_path.chmod(0o600)
    bundle_path.write_bytes(canonical_json_bytes(envelope) + b"\n")


def _rewrite_fault_closure_evidence(
    artifact_root: Path,
    evidence: dict[str, object],
    mutate,
) -> None:
    closure_artifact = next(
        item
        for item in evidence["artifacts"]
        if item["artifact_id"]
        == evidence["fault_injection"]["negative_state_closure_artifact_id"]
    )
    closure_path = artifact_root / str(closure_artifact["relative_path"])
    document = json.loads(closure_path.read_text(encoding="utf-8"))
    mutate(document["negative_state_closure"])
    content = canonical_json_bytes(document) + b"\n"
    closure_path.write_bytes(content)
    digest = _digest_bytes(content)
    evidence["fault_injection"]["negative_state_closure_digest"] = digest
    evidence["report"]["content_digest"] = digest
    product_path = evidence["product_path"]
    stale_snapshot_ids = {
        str(product_path.get("public_final_workspace_artifact_id") or ""),
        str(product_path.get("public_final_event_replay_artifact_id") or ""),
    }
    evidence["artifacts"] = [
        item
        for item in evidence["artifacts"]
        if str(item.get("artifact_id") or "") not in stale_snapshot_ids
    ]
    _attach_public_final_snapshot_fixture(artifact_root, evidence)


@pytest.mark.parametrize(
    ("tamper", "expected_code"),
    (
        ("config_payload", "effective_config_attestation_invalid"),
        ("config_digest", "effective_config_attestation_invalid"),
        ("ledger_identity", "micu_ledger_identity_changed"),
        ("approval_decision", "approval_chain_invalid"),
    ),
)
def test_launch_attestation_tamper_fails_closed(
    tmp_path: Path,
    tamper: str,
    expected_code: str,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    def mutate_launch_attestation(envelope: dict[str, object]) -> None:
        payload = envelope["payload"]
        launch = payload["product_path"]["launch_receipt"]
        if tamper == "config_payload":
            launch["effective_config"]["llm"]["enabled"] = False
        elif tamper == "config_digest":
            launch["effective_config_digest"] = _digest("tampered-config")
        elif tamper == "ledger_identity":
            payload["micu_ledger"]["before"]["ledger_identity_digest"] = _digest(
                "tampered-ledger"
            )
        else:
            approval = next(
                item
                for item in payload["approvals"]
                if item["operation_id"] == "op_hmmbuild"
            )
            approval["decision"] = "rejected"
        envelope["bundle_digest"] = canonical_digest(payload)

    _rewrite_envelope(bundle_path, mutate_launch_attestation)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(issue.code == expected_code for issue in result.issues)


@pytest.mark.parametrize(
    ("tamper", "expected_identity"),
    (
        ("missing_top_level", "effective_config"),
        ("extra_top_level", "effective_config"),
        ("missing_nested", "effective_config.llm"),
        ("extra_nested", "effective_config.host"),
        ("invalid_nested_type", "effective_config.limits.global"),
        (
            "invalid_nested_range",
            "effective_config.research.provider_timeout_seconds",
        ),
        (
            "extra_runner_contract_field",
            "effective_config.execution.aox_runner_contract_expectations.contracts.bio_tools.mafft",
        ),
    ),
)
def test_effective_config_closed_schema_tamper_is_rejected_offline(
    tmp_path: Path,
    tamper: str,
    expected_identity: str,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    def mutate_effective_config(envelope: dict[str, object]) -> None:
        payload = envelope["payload"]
        launch = payload["product_path"]["launch_receipt"]
        config = launch["effective_config"]
        if tamper == "missing_top_level":
            config.pop("tracing")
        elif tamper == "extra_top_level":
            config["legacy_compatibility"] = True
        elif tamper == "missing_nested":
            config["llm"].pop("model")
        elif tamper == "extra_nested":
            config["host"]["legacy_mode"] = False
        elif tamper == "invalid_nested_type":
            config["limits"]["global"] = True
        elif tamper == "invalid_nested_range":
            config["research"]["provider_timeout_seconds"] = 0.0
        else:
            config["execution"]["aox_runner_contract_expectations"]["contracts"][
                "bio_tools.mafft"
            ]["legacy_template"] = "fallback"
        config_digest = canonical_digest(config)
        launch["effective_config_digest"] = config_digest
        payload["product_path"]["runtime_config_digest"] = config_digest
        payload["identity"]["config_digest"] = config_digest
        payload["identity"]["identity_digest"] = canonical_digest(
            {
                key: value
                for key, value in payload["identity"].items()
                if key != "identity_digest"
            }
        )
        prerequisites = payload["clean_world"]["allowed_prerequisites"]
        prerequisites["config_digest"] = config_digest
        payload["clean_world"]["allowed_prerequisite_digest"] = canonical_digest(
            prerequisites
        )
        envelope["bundle_digest"] = canonical_digest(payload)

    _rewrite_envelope(bundle_path, mutate_effective_config)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "effective_config_attestation_invalid"
        and issue.identity == expected_identity
        for issue in result.issues
    )


@pytest.mark.parametrize("tamper", ("digest", "sequence", "route"))
def test_public_api_receipt_chain_tamper_fails_offline_verification(
    tmp_path: Path,
    tamper: str,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    def mutate_public_receipts(envelope: dict[str, object]) -> None:
        payload = envelope["payload"]
        product_path = payload["product_path"]
        receipts = product_path["public_api_receipts"]
        launch = product_path["launch_receipt"]
        if tamper == "digest":
            receipts[0]["response_digest"] = _digest("tampered-response")
        elif tamper == "sequence":
            receipts[1]["sequence"] = 9
            launch["public_api_receipt_digest"] = canonical_digest(receipts)
        else:
            receipts[0]["route"] = "/v3/internal/driver-shortcut"
            launch["public_api_receipt_digest"] = canonical_digest(receipts)
        envelope["bundle_digest"] = canonical_digest(payload)

    _rewrite_envelope(bundle_path, mutate_public_receipts)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "public_api_receipt_attestation_invalid"
        for issue in result.issues
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("image_digest", _digest("tampered-toolchain-image")),
        ("attestation_scope", "preflight_only"),
        ("tool_id", "bio_tools.compatibility_fallback"),
        ("adapter_id", "bio_tools.compatibility_fallback"),
        ("command_template_id", "compatibility_template_v1"),
        ("runner_contract_digest", _digest("tampered-runner-contract")),
    ),
)
def test_formal_toolchain_runtime_identity_tamper_fails_offline_verification(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    def mutate_toolchain_identity(envelope: dict[str, object]) -> None:
        payload = envelope["payload"]
        receipt = next(
            item for item in payload["toolchain_identities"] if item["tool"] == "mafft"
        )
        receipt[field] = value
        envelope["bundle_digest"] = canonical_digest(payload)

    _rewrite_envelope(bundle_path, mutate_toolchain_identity)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "toolchain_operation_receipt_mismatch" for issue in result.issues
    )


def test_blank_world_preflight_creates_unique_empty_roots_without_public_paths(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-clean",
        allowed_prerequisites=_allowed_prerequisites(),
    )

    assert not roots.sqlite_path.exists()
    assert all(
        path.is_dir() and list(path.iterdir()) == []
        for name, path in roots.local_paths().items()
        if name not in {"attempt_root", "sqlite_path"}
    )
    proof_text = json.dumps(roots.proof, sort_keys=True)
    assert str(tmp_path) not in proof_text
    assert roots.proof["provider_cache_mode"] == "bypass"
    assert roots.proof["evidence_cache_reuse"] is False


def test_blank_world_preflight_rejects_preloaded_science(tmp_path: Path) -> None:
    attempt_root = tmp_path / "campaign" / "positive-preloaded"
    attempt_root.mkdir(parents=True)
    (attempt_root / "AOX_candidates.fasta").write_text(">old\nMOLD\n", encoding="utf-8")

    with pytest.raises(CutoverEvidenceError) as error:
        create_blank_world_roots(
            tmp_path / "campaign",
            attempt_kind="positive",
            attempt_id="positive-preloaded",
            allowed_prerequisites=_allowed_prerequisites(),
        )

    assert error.value.code == "preloaded_science_detected"
    assert error.value.details["entries"] == ["AOX_candidates.fasta"]


def test_blank_world_preflight_rejects_science_in_allowed_prerequisites(
    tmp_path: Path,
) -> None:
    with pytest.raises(CutoverEvidenceError) as error:
        create_blank_world_roots(
            tmp_path / "campaign",
            attempt_kind="positive",
            attempt_id="positive-prerequisite",
            allowed_prerequisites={"alignment_fasta": ">cached\nMPEPTIDE\n"},
        )

    assert error.value.code == "allowed_prerequisite_schema_invalid"


def test_micu_snapshot_is_read_only_safe_and_keeps_the_fixed_ceiling(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "persistent-ledger.sqlite3"

    snapshot = safe_micu_ledger_snapshot(ledger)

    assert not ledger.exists()
    assert "path" not in snapshot
    assert snapshot["hard_limit_tokens"] == 500_000_000
    assert snapshot["charged_tokens"] == 0
    assert str(tmp_path) not in json.dumps(snapshot, sort_keys=True)


def test_untampered_positive_and_fault_bundles_verify_offline(tmp_path: Path) -> None:
    for attempt_kind in ("positive", "fault"):
        _, bundle_path, artifact_root = _build_bundle(
            tmp_path / attempt_kind,
            attempt_kind=attempt_kind,
        )

        result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

        assert result.passed, result.to_dict()
        assert result.attempt_kind == attempt_kind


@pytest.mark.parametrize(
    ("runtime_field", "identity_field"),
    (("image_digest", "image_digest"), ("pipeline_sdk_digest", "sdk_digest")),
)
def test_sandbox_preflight_identity_tamper_fails_offline_verification(
    tmp_path: Path,
    runtime_field: str,
    identity_field: str,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    def drift_runtime_identity(envelope: dict[str, object]) -> None:
        payload = envelope["payload"]
        launch = payload["product_path"]["launch_receipt"]
        launch["sandbox_runtime_identity"][runtime_field] = _digest(
            f"drift-{identity_field}"
        )
        envelope["bundle_digest"] = canonical_digest(payload)

    _rewrite_envelope(bundle_path, drift_runtime_identity)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "sandbox_runtime_identity_drift" for issue in result.issues
    )


def _browser_approval_receipt(payload: dict[str, object]) -> dict[str, object]:
    toolchain = next(
        item for item in payload["toolchain_identities"] if item["tool"] == "hmmbuild"
    )
    operation = next(
        item
        for item in payload["operations"]
        if item["operation_id"] == toolchain["operation_id"]
    )
    approval = next(
        item
        for item in payload["approvals"]
        if item["operation_id"] == toolchain["operation_id"]
    )
    product_path = payload["product_path"]
    session_id = str(product_path["session_id"])
    approval_id = str(approval["approval_id"])
    operation_id = str(operation["operation_id"])
    operation_digest = str(operation["operation_identity_digest"])
    continuation_id = "continuation_browser_001"
    pre_workspace = {
        "pending_approvals": [
            {
                "approval_id": approval_id,
                "operation": {
                    "operation_id": operation_id,
                    "operation_digest": operation_digest,
                },
            }
        ],
        "scientific_evidence": {"operations": []},
    }
    post_workspace = {
        "pending_approvals": [],
        "scientific_evidence": {
            "operations": [
                {
                    "operation_id": operation_id,
                    "operation_digest": operation_digest,
                    "approval_id": approval_id,
                    "approval_state": "approved",
                    "status": "waiting_approval",
                }
            ]
        },
    }
    resolution_event = {
        "event_id": "event_browser_resolution",
        "session_id": session_id,
        "event_type": "approval.resolved",
        "schema_version": "openzyme.v3.event.v1",
        "visibility": "public",
        "actor_ref": "local-user",
        "command_id": "command_browser_resolution",
        "created_at": "2026-07-17T00:00:10+00:00",
        "cursor": 11,
        "payload": {
            "approval_id": approval_id,
            "decision": "approved",
            "actor_ref": "local-user",
        },
    }
    continuation_event = {
        "event_id": "event_browser_continuation",
        "session_id": session_id,
        "event_type": "sdk_controlled_operation.approval_resolved",
        "schema_version": "openzyme.v3.event.v1",
        "visibility": "public",
        "actor_ref": None,
        "command_id": None,
        "created_at": "2026-07-17T00:00:11+00:00",
        "cursor": 12,
        "payload": {
            "approval_id": approval_id,
            "operation_id": operation_id,
            "operation_digest": operation_digest,
            "continuation_id": continuation_id,
            "decision": "approved",
        },
    }

    def closed_event(event: dict[str, object]) -> dict[str, object]:
        return {
            "schema_id": "aox_browser_durable_event@1",
            **event,
            "payload_digest": canonical_digest(event["payload"]),
        }

    event_records = [resolution_event, continuation_event]
    receipts = _public_api_receipts(session_id)[:4]
    receipts.extend(
        [
            {
                "sequence": 5,
                "method": "GET",
                "route": f"/v3/sessions/{session_id}/workspace",
                "status_code": 200,
                "request_digest": canonical_digest({}),
                "response_digest": _digest("browser-pre-workspace-response"),
                "response_semantic_digest": canonical_digest(pre_workspace),
            },
            {
                "sequence": 6,
                "method": "GET",
                "route": (
                    f"/v3/sessions/{session_id}/events?replay=1&after_cursor=10"
                ),
                "status_code": 200,
                "request_digest": canonical_digest(
                    {"replay": True, "after_cursor": 10}
                ),
                "response_digest": _digest("browser-events-response"),
                "response_semantic_digest": canonical_digest(event_records),
            },
            {
                "sequence": 7,
                "method": "GET",
                "route": f"/v3/sessions/{session_id}/workspace",
                "status_code": 200,
                "request_digest": canonical_digest({}),
                "response_digest": _digest("browser-post-workspace-response"),
                "response_semantic_digest": canonical_digest(post_workspace),
            },
            {
                "sequence": 8,
                "method": "GET",
                "route": f"/v3/sessions/{session_id}/workspace",
                "status_code": 200,
                "request_digest": canonical_digest({}),
                "response_digest": _digest("public-final-workspace-response"),
                "response_semantic_digest": product_path[
                    "public_final_workspace_digest"
                ],
            },
            {
                "sequence": 9,
                "method": "GET",
                "route": (
                    f"/v3/sessions/{session_id}/events?replay=1&after_cursor=0"
                ),
                "status_code": 200,
                "request_digest": canonical_digest(
                    {"replay": True, "after_cursor": 0}
                ),
                "response_digest": _digest("public-final-events-response"),
                "response_semantic_digest": product_path[
                    "public_final_event_stream_digest"
                ],
            },
        ]
    )
    product_path["public_api_receipts"] = receipts
    product_path["public_final_workspace_response_binding"] = {
        "receipt_sequence": 8,
        "route": f"/v3/sessions/{session_id}/workspace",
        "response_digest": _digest("public-final-workspace-response"),
        "response_semantic_digest": product_path["public_final_workspace_digest"],
    }
    product_path["public_final_event_response_binding"] = {
        "receipt_sequence": 9,
        "route": f"/v3/sessions/{session_id}/events?replay=1&after_cursor=0",
        "response_digest": _digest("public-final-events-response"),
        "response_semantic_digest": product_path[
            "public_final_event_stream_digest"
        ],
    }
    receipt = {
        "schema_id": "aox_browser_approval_receipt@2",
        "approval_mode": "chrome-once",
        "ui_channel": "same_process_loopback_web_ui",
        "host_process_id": 1234,
        "session_id": session_id,
        "approval_id": approval_id,
        "operation_id": operation_id,
        "operation_digest": operation_digest,
        "sandbox_workspace_id": operation["operation_identity_material"][
            "sandbox_workspace_id"
        ],
        "sandbox_run_id": operation["sandbox_run_id"],
        "page_url": (
            "loopback://same-process/ui/?project_id=aox-blank-world-cutover"
        ),
        "served_ui_dist_digest": _digest("ui-dist"),
        "observation_challenge": _digest("browser-observation-challenge"),
        "pre_workspace_snapshot": pre_workspace,
        "pre_workspace_digest": canonical_digest(pre_workspace),
        "pre_workspace_response_binding": {
            "receipt_sequence": 5,
            "route": f"/v3/sessions/{session_id}/workspace",
            "response_digest": _digest("browser-pre-workspace-response"),
            "response_semantic_digest": canonical_digest(pre_workspace),
        },
        "pre_event_cursor": 10,
        "resolution_event_id": "event_browser_resolution",
        "resolution_event_cursor": 11,
        "resolution_actor_ref": "local-user",
        "resolution_command_id": "command_browser_resolution",
        "resolution_event_record": closed_event(resolution_event),
        "continuation_event_id": "event_browser_continuation",
        "continuation_event_cursor": 12,
        "continuation_id": continuation_id,
        "continuation_event_record": closed_event(continuation_event),
        "event_response_bindings": [
            {
                "receipt_sequence": 6,
                "route": (
                    f"/v3/sessions/{session_id}/events?replay=1&after_cursor=10"
                ),
                "response_digest": _digest("browser-events-response"),
                "response_semantic_digest": canonical_digest(event_records),
                "event_records": event_records,
                "event_records_digest": canonical_digest(event_records),
            }
        ],
        "post_workspace_snapshot": post_workspace,
        "post_workspace_digest": canonical_digest(post_workspace),
        "post_workspace_response_binding": {
            "receipt_sequence": 7,
            "route": f"/v3/sessions/{session_id}/workspace",
            "response_digest": _digest("browser-post-workspace-response"),
            "response_semantic_digest": canonical_digest(post_workspace),
        },
        "post_operation_status": "waiting_approval",
        "driver_resolve_route_absent": True,
    }
    page_target_id = "chrome-page-aox-001"
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    screenshot_digest = _digest_bytes(png_bytes)
    page_state = {
        "session_id": session_id,
        "approval_id": approval_id,
        "operation_id": operation_id,
        "operation_digest": operation_digest,
        "approval_present": False,
        "operation_status": operation["status"],
        "final_master_response_id": product_path["final_master_response_id"],
        "report_id": payload["report"]["report_id"],
        "report_status": payload["report"]["status"],
        "scientific_evidence_digest": product_path[
            "public_final_scientific_evidence_digest"
        ],
        "workspace_digest": product_path["public_final_workspace_digest"],
        "workspace_response_binding": product_path[
            "public_final_workspace_response_binding"
        ],
        "event_stream_digest": product_path["public_final_event_stream_digest"],
        "event_last_cursor": product_path["public_final_event_last_cursor"],
        "event_response_binding": product_path[
            "public_final_event_response_binding"
        ],
    }
    transcript = [
        {
            "sequence": sequence,
            "tool": "chrome_devtools_mcp",
            "method": method,
            "page_target_id": page_target_id,
            "request_digest": _digest(f"chrome-{method}-request"),
            "response_digest": _digest(f"chrome-{method}-response"),
        }
        for sequence, method in enumerate(
            ("list_console_messages", "evaluate_script", "take_screenshot"),
            start=1,
        )
    ]
    command_id = "chrome-observation-command-001"
    command_digest = canonical_digest(
        {
            "tool": "chrome_devtools_mcp",
            "command_id": command_id,
            "page_target_id": page_target_id,
            "observation_challenge": receipt["observation_challenge"],
            "action": "observe_console_page_state_and_screenshot",
        }
    )
    response_digest = canonical_digest(
        {
            "page_state": page_state,
            "console_entries": [],
            "application_error_count": 0,
            "devtools_transcript_digest": canonical_digest(transcript),
            "screenshot_digest": screenshot_digest,
        }
    )
    payload["product_path"]["launch_receipt"]["browser_observation_receipt"] = {
        "schema_id": "aox_browser_observation_receipt@2",
        "observation_mode": "chrome_devtools_mcp_file_handoff",
        "observation_challenge": receipt["observation_challenge"],
        "session_id": session_id,
        "approval_id": approval_id,
        "operation_id": operation_id,
        "page_url": receipt["page_url"],
        "host_process_id": 1234,
        "served_ui_dist_digest": _digest("ui-dist"),
        "page_target_id": page_target_id,
        "observation_window_seconds": 60.0,
        "console_entries": [],
        "console_entries_digest": canonical_digest([]),
        "application_error_count": 0,
        "page_state": page_state,
        "page_state_digest": canonical_digest(page_state),
        "devtools_command_receipt": {
            "command_id": command_id,
            "tool": "chrome_devtools_mcp",
            "command_digest": command_digest,
            "response_digest": response_digest,
            "page_target_id": page_target_id,
        },
        "devtools_transcript": transcript,
        "devtools_transcript_digest": canonical_digest(transcript),
        "screenshot_png_base64": base64.b64encode(png_bytes).decode("ascii"),
        "screenshot_digest": screenshot_digest,
        "screenshot_width": 1,
        "screenshot_height": 1,
        "host_observation_hold_seconds": 60.0,
        "host_observation_hold_satisfied": True,
        "host_observation_submission_timeout_seconds": 180.0,
        "host_observation_ready_at_unix_ns": 1_000_000_000_000,
        "host_observation_not_before_unix_ns": 1_060_000_000_000,
        "host_observation_accepted_at_unix_ns": 1_060_000_000_001,
    }
    return receipt


def _attach_browser_receipt_artifacts(
    payload: dict[str, object],
    *,
    artifact_root: Path,
    browser_receipt: dict[str, object],
) -> None:
    launch = payload["product_path"]["launch_receipt"]
    launch["browser_approval_receipt"] = browser_receipt
    launch["public_api_receipt_digest"] = canonical_digest(
        payload["product_path"]["public_api_receipts"]
    )
    browser_events = [
        browser_receipt["resolution_event_record"],
        browser_receipt["continuation_event_record"],
    ]
    event_artifact = next(
        item
        for item in payload["artifacts"]
        if item["artifact_id"] == payload["product_path"]["event_log_artifact_id"]
    )
    event_path = artifact_root / event_artifact["relative_path"]
    event_payload = json.loads(event_path.read_text(encoding="utf-8"))
    event_payload["browser_approval_events"] = browser_events
    event_payload["browser_approval_event_stream_digest"] = canonical_digest(
        browser_events
    )
    event_bytes = canonical_json_bytes(event_payload) + b"\n"
    event_path.write_bytes(event_bytes)
    event_artifact["content_digest"] = _digest_bytes(event_bytes)
    event_artifact["size_bytes"] = len(event_bytes)
    if "record_digest" in event_artifact:
        event_artifact["record_digest"] = canonical_digest(
            {
                key: value
                for key, value in event_artifact.items()
                if key != "record_digest"
            }
        )
    payload["product_path"]["event_log_digest"] = _digest_bytes(event_bytes)
    payload["product_path"]["browser_approval_event_stream_digest"] = (
        canonical_digest(browser_events)
    )
    for artifact_id_key, binding_key, digest_key in (
        (
            "public_final_workspace_artifact_id",
            "public_final_workspace_response_binding",
            "public_final_workspace_artifact_digest",
        ),
        (
            "public_final_event_replay_artifact_id",
            "public_final_event_response_binding",
            "public_final_event_replay_artifact_digest",
        ),
    ):
        attestation_artifact = next(
            item
            for item in payload["artifacts"]
            if item["artifact_id"] == payload["product_path"][artifact_id_key]
        )
        attestation_path = artifact_root / attestation_artifact["relative_path"]
        attestation_payload = json.loads(
            attestation_path.read_text(encoding="utf-8")
        )
        attestation_payload["response_binding"] = payload["product_path"][
            binding_key
        ]
        attestation_bytes = canonical_json_bytes(attestation_payload) + b"\n"
        attestation_path.write_bytes(attestation_bytes)
        attestation_digest = _digest_bytes(attestation_bytes)
        attestation_artifact["content_digest"] = attestation_digest
        attestation_artifact["size_bytes"] = len(attestation_bytes)
        if "record_digest" in attestation_artifact:
            attestation_artifact["record_digest"] = canonical_digest(
                {
                    key: value
                    for key, value in attestation_artifact.items()
                    if key != "record_digest"
                }
            )
        payload["product_path"][digest_key] = attestation_digest


def _enable_chrome_once_receipt(
    payload: dict[str, object],
    *,
    artifact_root: Path,
) -> None:
    launch = payload["product_path"]["launch_receipt"]
    launch["approval_mode"] = "chrome-once"
    launch["campaign_attempt_number"] = 1
    config = json.loads(json.dumps(launch["effective_config"]))
    config["driver"]["approval_mode"] = "chrome-once"
    config["driver"]["ui_dist_digest"] = _digest("ui-dist")
    config_digest = canonical_digest(config)
    launch["effective_config"] = config
    launch["effective_config_digest"] = config_digest
    payload["product_path"]["runtime_config_digest"] = config_digest
    payload["identity"]["config_digest"] = config_digest
    payload["identity"]["identity_digest"] = canonical_digest(
        {
            key: value
            for key, value in payload["identity"].items()
            if key != "identity_digest"
        }
    )
    clean_world = payload["clean_world"]
    clean_world["allowed_prerequisites"]["config_digest"] = config_digest
    clean_world["allowed_prerequisite_digest"] = canonical_digest(
        clean_world["allowed_prerequisites"]
    )
    workspace_artifact = next(
        item
        for item in payload["artifacts"]
        if item["artifact_id"]
        == payload["product_path"]["workspace_projection_artifact_id"]
    )
    workspace_path = artifact_root / workspace_artifact["relative_path"]
    workspace_payload = json.loads(workspace_path.read_text(encoding="utf-8"))
    workspace_payload["runtime_config_digest"] = config_digest
    workspace_bytes = canonical_json_bytes(workspace_payload) + b"\n"
    workspace_path.write_bytes(workspace_bytes)
    workspace_digest = _digest_bytes(workspace_bytes)
    workspace_artifact["content_digest"] = workspace_digest
    workspace_artifact["size_bytes"] = len(workspace_bytes)
    workspace_artifact["record_digest"] = canonical_digest(
        {
            key: value
            for key, value in workspace_artifact.items()
            if key != "record_digest"
        }
    )
    payload["product_path"]["workspace_projection_digest"] = workspace_digest
    browser_receipt = _browser_approval_receipt(payload)
    _attach_browser_receipt_artifacts(
        payload,
        artifact_root=artifact_root,
        browser_receipt=browser_receipt,
    )


def test_chrome_once_same_operation_receipt_verifies_offline(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    def attach_receipt(envelope: dict[str, object]) -> None:
        payload = envelope["payload"]
        _enable_chrome_once_receipt(payload, artifact_root=artifact_root)
        envelope["bundle_digest"] = canonical_digest(payload)

    _rewrite_envelope(bundle_path, attach_receipt)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed, result.to_dict()


@pytest.mark.parametrize(
    ("tamper", "expected_code"),
    (
        ("missing", "browser_approval_receipt_missing"),
        ("operation_digest", "browser_approval_receipt_invalid"),
    ),
)
def test_chrome_once_receipt_tamper_fails_offline_verification(
    tmp_path: Path,
    tamper: str,
    expected_code: str,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    def mutate_receipt(envelope: dict[str, object]) -> None:
        payload = envelope["payload"]
        _enable_chrome_once_receipt(payload, artifact_root=artifact_root)
        launch = payload["product_path"]["launch_receipt"]
        if tamper == "missing":
            launch["browser_approval_receipt"] = None
        else:
            launch["browser_approval_receipt"][tamper] = _digest("drift")
        envelope["bundle_digest"] = canonical_digest(payload)

    _rewrite_envelope(bundle_path, mutate_receipt)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(issue.code == expected_code for issue in result.issues)


@pytest.mark.parametrize(
    "tamper",
    (
        "accepted_before_window_end",
        "accepted_after_submission_deadline",
        "window_duration_drift",
        "submission_timeout_drift",
    ),
)
def test_chrome_observation_host_timing_tamper_fails_offline_verification(
    tmp_path: Path,
    tamper: str,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    def mutate_timing(envelope: dict[str, object]) -> None:
        payload = envelope["payload"]
        _enable_chrome_once_receipt(payload, artifact_root=artifact_root)
        receipt = payload["product_path"]["launch_receipt"][
            "browser_observation_receipt"
        ]
        if tamper == "accepted_before_window_end":
            receipt["host_observation_accepted_at_unix_ns"] = (
                receipt["host_observation_not_before_unix_ns"] - 1
            )
        elif tamper == "accepted_after_submission_deadline":
            receipt["host_observation_accepted_at_unix_ns"] = (
                receipt["host_observation_not_before_unix_ns"]
                + 180_000_000_001
            )
        elif tamper == "window_duration_drift":
            receipt["host_observation_not_before_unix_ns"] += 1
        else:
            receipt["host_observation_submission_timeout_seconds"] = 181.0
        envelope["bundle_digest"] = canonical_digest(payload)

    _rewrite_envelope(bundle_path, mutate_timing)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "browser_approval_receipt_invalid"
        for issue in result.issues
    )


def test_chrome_once_rejects_sealed_driver_resolve_route_receipt(
    tmp_path: Path,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    def attach_driver_shortcut(envelope: dict[str, object]) -> None:
        payload = envelope["payload"]
        _enable_chrome_once_receipt(payload, artifact_root=artifact_root)
        product_path = payload["product_path"]
        launch = product_path["launch_receipt"]
        browser = launch["browser_approval_receipt"]
        receipts = product_path["public_api_receipts"]
        receipts.append(
            {
                "sequence": len(receipts) + 1,
                "method": "POST",
                "route": f"/v3/approvals/{browser['approval_id']}/resolve",
                "status_code": 200,
                    "request_digest": canonical_digest({"decision": "approved"}),
                    "response_digest": _digest("driver-approval-response"),
                    "response_semantic_digest": _digest(
                        "driver-approval-semantic"
                    ),
            }
        )
        launch["public_api_receipt_digest"] = canonical_digest(receipts)
        envelope["bundle_digest"] = canonical_digest(payload)

    _rewrite_envelope(bundle_path, attach_driver_shortcut)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "browser_approval_driver_shortcut_detected"
        for issue in result.issues
    )


def test_nonempty_reference_chain_uses_exact_14_13_aab_plus_target_contract(
    tmp_path: Path,
) -> None:
    payload, bundle_path, artifact_root = _build_bundle(tmp_path)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed, result.to_dict()
    chain = payload["scientific_checks"]["aox_chain"]
    assert chain["operation_roles"] == {
        **chain["operation_roles"],
        "hmm_reference_set_selection": "op_hmm_reference_set_selection",
        "scoring_reference_selection": "op_scoring_reference_selection",
        "scoring_input_assembly": "op_scoring_input_assembly",
    }
    artifact_by_id = {
        artifact["artifact_id"]: artifact for artifact in payload["artifacts"]
    }

    def artifact_bytes(role: str) -> bytes:
        artifact = artifact_by_id[chain["artifact_roles"][role]]
        return (artifact_root / artifact["relative_path"]).read_bytes()

    ncbi_bytes = artifact_bytes("ncbi_provider_sequences")
    hmm_reference_set_bytes = artifact_bytes("hmm_reference_set")
    scoring_reference_bytes = artifact_bytes("scoring_reference")
    target_bytes = artifact_bytes("target_sequences")
    scoring_input_bytes = artifact_bytes("scoring_input")
    hmm_result = aox_reference.select_hmm_reference_set(ncbi_bytes)
    scoring_reference_result = aox_reference.select_scoring_reference(ncbi_bytes)
    scoring_input_result = aox_reference.assemble_scoring_input(
        scoring_reference_bytes,
        target_bytes,
    )
    assert len(hmm_result.source_records) == 14
    assert [record.sequence_id for record in hmm_result.selected_records] == list(
        aox_reference.HMM_REFERENCE_ACCESSIONS
    )
    assert hmm_reference_set_bytes == hmm_result.to_fasta().encode("utf-8")
    assert scoring_reference_bytes == scoring_reference_result.to_fasta().encode(
        "utf-8"
    )
    assert scoring_input_bytes == scoring_input_result.to_fasta().encode("utf-8")
    assert scoring_input_result.records[0].sequence_id == "AAB57849.1"
    assert len(scoring_input_result.targets) > 0
    operations = {
        operation["operation_id"]: operation for operation in payload["operations"]
    }
    assert {item["artifact_id"] for item in operations["op_hmmalign"]["inputs"]} == {
        "art_hmm_model",
        "art_scoring_input",
    }


@pytest.mark.parametrize(
    "scientific_branch",
    ["nonempty", "hmmer_upstream_empty"],
)
def test_reference_chain_contract_tamper_fails_closed(
    tmp_path: Path,
    scientific_branch: str,
) -> None:
    def tamper_scoring_input_contract(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_scoring_input_assembly"
        )
        operation["parameters"] = {
            **dict(operation["parameters"]),
            "target_count": int(operation["parameters"]["target_count"]) + 1,
        }
        _refresh_sandbox_calculation_identity(operation)

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        scientific_branch=scientific_branch,
        mutate_evidence=tamper_scoring_input_contract,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(issue.code == "aox_reference_chain_invalid" for issue in result.issues)


@pytest.mark.parametrize(
    "scientific_branch",
    ["nonempty", "hmmer_upstream_empty"],
)
def test_reference_chain_rejects_rebound_incomplete_ncbi_provider_set(
    tmp_path: Path,
    scientific_branch: str,
) -> None:
    artifact_root = tmp_path / "campaign" / "positive-one" / "artifacts"

    def drop_coordinate_reference(evidence: dict[str, object]) -> None:
        artifact = next(
            item
            for item in evidence["artifacts"]
            if item["artifact_id"] == "art_ncbi_provider_sequences"
        )
        path = artifact_root / str(artifact["relative_path"])
        incomplete = path.read_bytes().rsplit(b">AAB57849.1\n", maxsplit=1)[0]
        digest = _replace_artifact_bytes(
            artifact_root,
            evidence,
            artifact_id="art_ncbi_provider_sequences",
            content=incomplete,
        )
        provider = next(
            item
            for item in evidence["provider_identities"]
            if item["provider"] == "ncbi"
        )
        provider["response_digest"] = digest
        _refresh_fixture_operation_identities(evidence)

    _, bundle_path, sealed_root = _build_bundle(
        tmp_path,
        scientific_branch=scientific_branch,
        mutate_evidence=drop_coordinate_reference,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=sealed_root)

    assert result.passed is False
    assert any(issue.code == "aox_reference_chain_invalid" for issue in result.issues)


def _wrap_ncbi_response_as_raw_envelope(
    evidence: dict[str, object],
    *,
    artifact_root: Path,
    malformed_tail: bool = False,
) -> None:
    reference_artifact = next(
        item
        for item in evidence["artifacts"]
        if item["artifact_id"] == "art_ncbi_provider_sequences"
    )
    reference_path = artifact_root / reference_artifact["relative_path"]
    raw = reference_path.read_bytes()
    raw_response_body = raw + b"\n"
    raw_digest = _digest_bytes(raw_response_body)
    response = {
        "ordinal": 1,
        "phase": "efetch",
        "status_code": 200,
        "headers": {},
        "body_encoding": "base64",
        "body_base64": base64.b64encode(raw_response_body).decode("ascii"),
        "body_digest": raw_digest,
        "size_bytes": len(raw_response_body),
    }
    responses = [response]
    if malformed_tail:
        responses.append(
            {
                **response,
                "ordinal": 2,
                "phase": "followup",
                "body_digest": _digest("wrong-tail-body"),
            }
        )
    envelope = {
        "schema_id": "provider_raw_http_response_set@1",
        "provider": "ncbi",
        "operation": "bio.ncbi_fetch_proteins",
        "responses": responses,
    }
    wrapped = canonical_json_bytes(envelope) + b"\n"
    raw_relative_path = "formal/provider/ncbi-raw-response.json"
    raw_path = artifact_root / raw_relative_path
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(wrapped)
    wrapped_digest = _digest_bytes(wrapped)
    provider = next(
        item for item in evidence["provider_identities"] if item["provider"] == "ncbi"
    )
    provider["response_digest"] = raw_digest
    provider["artifact_ids"].append("art_ncbi_raw_response")
    ncbi_operation = next(
        item for item in evidence["operations"] if item["operation_id"] == "op_ncbi"
    )
    ncbi_operation["outputs"].append(
        {
            "artifact_id": "art_ncbi_raw_response",
            "content_digest": wrapped_digest,
        }
    )
    _refresh_operation_identity(ncbi_operation)
    evidence["artifacts"].append(
        {
            "artifact_id": "art_ncbi_raw_response",
            "relative_path": raw_relative_path,
            "scope": "formal",
            "origin": "operation",
            "kind": "provider_evidence",
            "provenance": {
                "operation_id": "op_ncbi",
                "provider": "ncbi",
                "provider_artifact_kind": "provider_raw",
            },
        }
    )
    evidence["artifacts"] = [
        item for item in evidence["artifacts"] if item.get("origin") != "attestation"
    ]
    _attach_product_receipts(artifact_root, evidence, run_suffix=None)
    _attach_public_final_snapshot_fixture(artifact_root, evidence)


def test_provider_response_digest_can_be_recomputed_from_raw_byte_envelope(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "campaign" / "positive-one" / "artifacts"

    def wrap_ncbi_response(evidence: dict[str, object]) -> None:
        _wrap_ncbi_response_as_raw_envelope(
            evidence,
            artifact_root=artifact_root,
        )

    _, bundle_path, sealed_root = _build_bundle(
        tmp_path,
        mutate_evidence=wrap_ncbi_response,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=sealed_root)

    assert result.passed, result.to_dict()


def test_provider_raw_envelope_validates_all_responses_before_digest_match(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "campaign" / "positive-one" / "artifacts"

    def add_malformed_tail(evidence: dict[str, object]) -> None:
        _wrap_ncbi_response_as_raw_envelope(
            evidence,
            artifact_root=artifact_root,
            malformed_tail=True,
        )

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=add_malformed_tail)

    assert error.value.code == "provider_artifact_lineage_invalid"


def test_fault_bundle_proves_real_byte_flip_and_terminal_failed_operation(
    tmp_path: Path,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
    )
    envelope = json.loads(bundle_path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    fault = payload["fault_injection"]
    target = artifact_root / fault["relative_path"]
    mutated = target.read_bytes()
    restored = bytearray(mutated)
    restored[fault["byte_offset"]] ^= 1
    operations = {item["operation_id"]: item for item in payload["operations"]}

    assert fault["after_digest"] == _digest_bytes(mutated)
    assert fault["before_digest"] == _digest_bytes(bytes(restored))
    assert operations[fault["terminal_failure_operation_id"]]["status"] == "failed"
    assert operations[fault["terminal_failure_operation_id"]]["inputs"] == [
        {
            "artifact_id": fault["target_artifact_id"],
            "content_digest": fault["before_digest"],
        }
    ]
    assert verify_attempt_bundle(bundle_path, artifact_root=artifact_root).passed


def test_fault_self_declaration_cannot_replace_byte_proof(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
    )

    def forge(envelope):
        envelope["payload"]["fault_injection"]["before_digest"] = _digest("forged")
        envelope["bundle_digest"] = canonical_digest(envelope["payload"])

    _rewrite_envelope(bundle_path, forge)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "fault_byte_flip_proof_mismatch" for issue in result.issues
    )


@pytest.mark.parametrize("tamper", ("route", "accessions"))
def test_fault_source_requires_exact_ncbi_operation_contract(
    tmp_path: Path,
    tamper: str,
) -> None:
    def tamper_source(evidence: dict[str, object]) -> None:
        operation = next(
            item for item in evidence["operations"] if item["operation_id"] == "op_ncbi"
        )
        if tamper == "route":
            operation["route_policy_id"] = "compat.fake_provider.provider:v1"
        else:
            operation["parameters"] = {
                **dict(operation["parameters"]),
                "accessions": list(aox_reference.NCBI_REFERENCE_ACCESSIONS[:-1]),
            }
        _refresh_operation_identity(operation)
        approval = next(
            item
            for item in evidence["approvals"]
            if item["operation_id"] == operation["operation_id"]
        )
        approval["operation_identity_digest"] = operation["operation_identity_digest"]
        provider = evidence["provider_identities"][0]
        provider["request_digest"] = operation["params_digest"]

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
        mutate_evidence=tamper_source,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "fault_operation_attestation_invalid" for issue in result.issues
    )


def test_fault_consumer_requires_exact_mafft_toolchain_identity(tmp_path: Path) -> None:
    def tamper_consumer(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_align"
        )
        material = dict(operation["operation_identity_material"])
        material["toolchain_id"] = "compat_unpinned_runner:v1"
        operation["operation_identity_material"] = material
        operation["operation_identity_digest"] = controlled_operation_digest(material)
        approval = next(
            item
            for item in evidence["approvals"]
            if item["operation_id"] == operation["operation_id"]
        )
        approval["operation_identity_digest"] = operation["operation_identity_digest"]

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
        mutate_evidence=tamper_consumer,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "fault_operation_attestation_invalid" for issue in result.issues
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("tool_id", "bio_tools.compatibility_fallback"),
        ("adapter_id", "bio_tools.compatibility_fallback"),
        ("command_template_id", "compatibility_template_v1"),
        ("runner_contract_digest", _digest("wrong-runner-contract")),
    ),
)
def test_fault_consumer_runner_expectation_is_closed_over_effective_config(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    def tamper_runner_expectation(evidence: dict[str, object]) -> None:
        evidence["fault_injection"]["consumer_runner_contract_expectation"][field] = (
            value
        )

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
        mutate_evidence=tamper_runner_expectation,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "fault_operation_attestation_invalid" for issue in result.issues
    )


def test_fault_final_assistant_must_bind_exact_failure_code(tmp_path: Path) -> None:
    artifact_root = tmp_path / "campaign" / "fault-one" / "artifacts"

    def replace_with_success(evidence: dict[str, object]) -> None:
        success = "The AOX/HMM workflow is complete and ready for live cutover."
        evidence["final_answer"]["content"] = success

        def mutate_closure(closure: dict[str, object]) -> None:
            assistant = next(
                item
                for item in closure["conversation_receipts"]
                if item["role"] == "assistant"
            )
            assistant["content_digest"] = _digest_bytes(success.encode("utf-8"))

        _rewrite_fault_closure_evidence(
            artifact_root,
            evidence,
            mutate_closure,
        )

    _, bundle_path, sealed_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
        mutate_evidence=replace_with_success,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=sealed_root)

    assert any(
        issue.code == "fault_negative_state_closure_invalid" for issue in result.issues
    )


def test_fault_ready_draft_is_not_negative_state_closure(tmp_path: Path) -> None:
    artifact_root = tmp_path / "campaign" / "fault-one" / "artifacts"

    def add_ready_draft(evidence: dict[str, object]) -> None:
        def mutate_closure(closure: dict[str, object]) -> None:
            closure["draft_states"] = [
                {
                    "draft_id": "draft_hidden_success",
                    "task_id": "task_report",
                    "status": "ready",
                    "content_ref": "doc_hidden_success",
                    "published_report_id": None,
                }
            ]

        _rewrite_fault_closure_evidence(
            artifact_root,
            evidence,
            mutate_closure,
        )

    _, bundle_path, sealed_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
        mutate_evidence=add_ready_draft,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=sealed_root)

    assert any(
        issue.code == "fault_negative_state_closure_invalid" for issue in result.issues
    )


def test_fault_execution_task_cannot_complete(tmp_path: Path) -> None:
    artifact_root = tmp_path / "campaign" / "fault-one" / "artifacts"

    def complete_execution(evidence: dict[str, object]) -> None:
        task = next(item for item in evidence["tasks"] if item["role"] == "executor")
        task["status"] = "completed"
        task["finish_payload_digest"] = _digest("completed-execution-finish")

        def mutate_closure(closure: dict[str, object]) -> None:
            receipt = next(
                item
                for item in closure["task_receipts"]
                if item["task_id"] == task["task_id"]
            )
            receipt.update(task)

        _rewrite_fault_closure_evidence(
            artifact_root,
            evidence,
            mutate_closure,
        )

    _, bundle_path, sealed_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
        mutate_evidence=complete_execution,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=sealed_root)

    assert any(
        issue.code == "fault_negative_state_closure_invalid" for issue in result.issues
    )


def test_fault_alternate_target_consumer_cannot_succeed(tmp_path: Path) -> None:
    artifact_root = tmp_path / "campaign" / "fault-one" / "artifacts"

    def add_successful_consumer(evidence: dict[str, object]) -> None:
        fault = evidence["fault_injection"]
        operation = _operation(
            "op_alternate_mafft",
            inputs=[(fault["target_artifact_id"], fault["before_digest"])],
        )
        operation.update(
            {
                "task_id": "task_execute",
                "lane_id": "lane_execute",
                "route_policy_id": "bio_tools.mafft.hpc:v1",
                "selected_backend": "hpc",
                "backend_run_id": "job_alternate_mafft",
            }
        )
        _refresh_operation_identity(
            operation,
            hpc_workspace_label=evidence["product_path"]["hpc_workspace_binding"][
                "label"
            ],
        )
        evidence["operations"].append(operation)
        evidence["product_path"]["hpc_workspace_binding"]["workspace_ids"] = sorted(
            {
                *evidence["product_path"]["hpc_workspace_binding"]["workspace_ids"],
                operation["hpc_workspace_id"],
            }
        )
        material = dict(operation["operation_identity_material"])
        state = {
            "operation_id": operation["operation_id"],
            "task_id": operation["task_id"],
            "sdk_module": material["sdk_module"],
            "function_name": material["function_name"],
            "selected_backend": operation["selected_backend"],
            "status": operation["status"],
            "failure_code": None,
            "operation_identity_digest": operation["operation_identity_digest"],
        }

        def mutate_closure(closure: dict[str, object]) -> None:
            closure["consumer_states"].append(state)
            closure["consumer_states"].sort(key=lambda item: item["operation_id"])
            closure["successful_alternate_consumer_ids"] = [operation["operation_id"]]

        _rewrite_fault_closure_evidence(
            artifact_root,
            evidence,
            mutate_closure,
        )

    _, bundle_path, sealed_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
        mutate_evidence=add_successful_consumer,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=sealed_root)

    assert any(
        issue.code == "fault_negative_state_closure_invalid" for issue in result.issues
    )


def test_fault_closure_cannot_omit_public_task_from_final_snapshot(
    tmp_path: Path,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
    )

    def omit_task(envelope: dict[str, object]) -> None:
        payload = envelope["payload"]
        fault = payload["fault_injection"]
        closure_artifact = next(
            item
            for item in payload["artifacts"]
            if item["artifact_id"] == fault["negative_state_closure_artifact_id"]
        )
        closure_path = artifact_root / closure_artifact["relative_path"]
        document = json.loads(closure_path.read_text(encoding="utf-8"))
        document["negative_state_closure"]["task_receipts"].pop()
        content = canonical_json_bytes(document) + b"\n"
        closure_path.write_bytes(content)
        digest = _digest_bytes(content)
        closure_artifact["content_digest"] = digest
        closure_artifact["size_bytes"] = len(content)
        closure_artifact["record_digest"] = canonical_digest(
            {
                key: value
                for key, value in closure_artifact.items()
                if key != "record_digest"
            }
        )
        fault["negative_state_closure_digest"] = digest
        payload["report"]["content_digest"] = digest
        envelope["bundle_digest"] = canonical_digest(payload)

    _rewrite_envelope(bundle_path, omit_task)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "fault_negative_state_closure_invalid"
        for issue in result.issues
    )


def test_fault_unlisted_or_downstream_deliverable_is_rejected(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
    )
    hidden = artifact_root / "formal" / "report.md"
    hidden.write_text("# hidden success report\n", encoding="utf-8")

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "fault_negative_state_closure_invalid" for issue in result.issues
    )


def test_fault_declared_downstream_deliverable_is_rejected(tmp_path: Path) -> None:
    artifact_root = tmp_path / "campaign" / "fault-one" / "artifacts"

    def add_downstream_deliverable(evidence: dict[str, object]) -> None:
        _write_artifact(
            artifact_root,
            "aox_hmm/AOX_candidates.fasta",
            b">forbidden_success\nMAAA\n",
        )
        evidence["artifacts"].append(
            {
                "artifact_id": "art_forbidden_success",
                "relative_path": "aox_hmm/AOX_candidates.fasta",
                "scope": "formal",
                "origin": "attestation",
                "kind": "sequence",
                "provenance": {
                    "producer": "alternate_success_path",
                    "catalog_relative_path": "aox_hmm/AOX_candidates.fasta",
                },
            }
        )

    _, bundle_path, sealed_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
        mutate_evidence=add_downstream_deliverable,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=sealed_root)

    assert any(
        issue.code == "fault_negative_state_closure_invalid" for issue in result.issues
    )


def test_artifact_byte_tamper_reports_exact_artifact(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    fault = inject_artifact_byte_flip(
        artifact_root,
        relative_path="formal/motif-scores.csv",
        byte_offset=4,
    )
    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert fault["fault_id"] == FAULT_ARTIFACT_BYTE_FLIP_ID
    assert fault["reached_target_seam"] is True
    assert result.passed is False
    issue = next(
        item
        for item in result.issues
        if item.code == "artifact_content_digest_mismatch"
    )
    assert issue.identity == "artifact:art_scores:content"


def test_provenance_operation_report_and_bundle_tampering_are_located(
    tmp_path: Path,
) -> None:
    cases = {
        "provenance": (
            lambda envelope: envelope["payload"]["artifacts"][0]["provenance"].update(
                {"provider": "tampered"}
            ),
            "artifact_provenance_digest_mismatch",
        ),
        "operation": (
            lambda envelope: envelope["payload"]["operations"][0].update(
                {"status": "failed"}
            ),
            "record_digest_mismatch",
        ),
        "report": (
            lambda envelope: envelope["payload"]["report"].update({"status": "draft"}),
            "record_digest_mismatch",
        ),
        "bundle": (
            lambda envelope: envelope["payload"].update(
                {"warnings": ["tampered warning"]}
            ),
            "bundle_digest_mismatch",
        ),
    }
    for name, (mutate, expected_code) in cases.items():
        _, bundle_path, artifact_root = _build_bundle(tmp_path / name)
        _rewrite_envelope(bundle_path, mutate)

        result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

        assert result.passed is False
        assert expected_code in {issue.code for issue in result.issues}


def test_envelope_top_level_secret_is_rejected(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    _rewrite_envelope(
        bundle_path,
        lambda envelope: envelope.update({"api_key": "must-not-project"}),
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    codes = {issue.code for issue in result.issues}
    assert "bundle_envelope_invalid" in codes
    assert "public_projection_sensitive_key" in codes


def test_malformed_bundle_returns_issues_instead_of_crashing(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    _rewrite_envelope(
        bundle_path,
        lambda envelope: envelope["payload"].update({"report": "malformed"}),
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(issue.code == "bundle_field_type_invalid" for issue in result.issues)


def test_missing_artifact_issue_does_not_leak_host_path(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    (artifact_root / "formal/report.md").unlink()

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    issue = next(item for item in result.issues if item.code == "artifact_unreadable")
    assert str(tmp_path) not in issue.message


def test_eligible_positive_rejects_empty_provider_chain(tmp_path: Path) -> None:
    def remove_providers(evidence: dict[str, object]) -> None:
        evidence["provider_identities"] = []

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=remove_providers)

    assert error.value.code == "required_provider_chain_missing"


def test_delegation_workflow_binding_is_executor_scoped_and_offline_verified(
    tmp_path: Path,
) -> None:
    def leak_binding_to_researcher(evidence: dict[str, object]) -> None:
        tasks = [dict(item) for item in evidence["tasks"]]
        executor = next(item for item in tasks if item["role"] == "executor")
        researcher = next(item for item in tasks if item["role"] == "researcher")
        researcher["workflow_refs"] = list(executor["workflow_refs"])
        researcher["workflow_manifests"] = list(executor["workflow_manifests"])
        evidence["tasks"] = tasks

    with pytest.raises(CutoverEvidenceError) as build_error:
        _build_bundle(tmp_path / "build", mutate_evidence=leak_binding_to_researcher)
    assert build_error.value.code == "delegation_workflow_binding_invalid"

    _, bundle_path, artifact_root = _build_bundle(tmp_path / "offline")
    envelope = json.loads(bundle_path.read_text(encoding="utf-8"))
    executor = next(
        task
        for task in envelope["payload"]["tasks"]
        if task["role"] == "executor"
    )
    executor["workflow_manifests"][0]["summary"] = "attacker-rewritten summary"
    executor["delegation_request"]["workflow_manifests"][0]["summary"] = (
        "attacker-rewritten summary"
    )
    executor["delegation_request_digest"] = canonical_digest(
        executor["delegation_request"]
    )
    executor["record_digest"] = canonical_digest(
        {key: value for key, value in executor.items() if key != "record_digest"}
    )
    envelope["bundle_digest"] = canonical_digest(envelope["payload"])
    bundle_path.chmod(0o600)
    bundle_path.write_bytes(canonical_json_bytes(envelope) + b"\n")

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "delegation_workflow_manifest_invalid"
        for issue in result.issues
    )


def test_delegation_request_projection_tamper_is_rejected_after_outer_rehash(
    tmp_path: Path,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    envelope = json.loads(bundle_path.read_text(encoding="utf-8"))
    executor = next(
        task
        for task in envelope["payload"]["tasks"]
        if task["role"] == "executor"
    )
    executor["delegation_request_ref"] = "doc_attacker_rewritten"
    executor["delegation_request"]["document_id"] = "doc_attacker_rewritten"
    executor["delegation_request_digest"] = canonical_digest(
        executor["delegation_request"]
    )
    envelope["bundle_digest"] = canonical_digest(envelope["payload"])
    bundle_path.chmod(0o600)
    bundle_path.write_bytes(canonical_json_bytes(envelope) + b"\n")

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(issue.code == "record_digest_mismatch" for issue in result.issues)


def test_required_pubmed_receipt_must_bind_real_pmid_artifact(tmp_path: Path) -> None:
    def change_declared_pmid(evidence: dict[str, object]) -> None:
        provider = next(
            item
            for item in evidence["provider_identities"]
            if item["provider"] == "pubmed"
        )
        provider["source_refs"][0]["pmid"] = "87654321"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=change_declared_pmid)

    assert error.value.code == "pubmed_artifact_identity_mismatch"


def test_pubmed_primary_artifact_must_be_selected_by_researcher_task(
    tmp_path: Path,
) -> None:
    def remove_primary_selection(evidence: dict[str, object]) -> None:
        researcher = next(
            item for item in evidence["tasks"] if item["role"] == "researcher"
        )
        researcher["evidence_refs"] = []

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=remove_primary_selection)

    assert error.value.code == "pubmed_primary_task_binding_invalid"


def test_pubmed_primary_artifact_must_close_through_selected_invocation(
    tmp_path: Path,
) -> None:
    def drift_primary_artifact_role(evidence: dict[str, object]) -> None:
        evidence["scientific_checks"]["aox_chain"]["artifact_roles"][
            "literature_evidence"
        ] = "art_ncbi_provider_sequences"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=drift_primary_artifact_role)

    assert error.value.code == "pubmed_primary_lineage_invalid"


def test_pubmed_invocation_must_belong_to_researcher_task(tmp_path: Path) -> None:
    def move_invocation_to_executor(evidence: dict[str, object]) -> None:
        invocation = evidence["engine_invocations"][0]
        invocation["task_id"] = "task_execute"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=move_invocation_to_executor)

    assert error.value.code == "pubmed_invocation_task_mismatch"


def test_pubmed_invocation_allows_matching_absent_research_lane(tmp_path: Path) -> None:
    def remove_optional_lane(evidence: dict[str, object]) -> None:
        researcher = next(
            item for item in evidence["tasks"] if item["role"] == "researcher"
        )
        researcher["lane_id"] = None
        evidence["engine_invocations"][0]["lane_id"] = None
        primary = next(
            item
            for item in evidence["artifacts"]
            if item["artifact_id"] == "art_pubmed_response"
        )
        primary["provenance"]["lane_id"] = None
        pubmed = next(
            item
            for item in evidence["provider_identities"]
            if item["provider"] == "pubmed"
        )
        pubmed["source_refs"][0]["lane_id"] = None

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=remove_optional_lane,
    )

    assert verify_attempt_bundle(bundle_path, artifact_root=artifact_root).passed is True


def test_pubmed_invocation_lane_must_match_researcher_task(tmp_path: Path) -> None:
    def drift_invocation_lane(evidence: dict[str, object]) -> None:
        evidence["engine_invocations"][0]["lane_id"] = None

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=drift_invocation_lane)

    assert error.value.code == "pubmed_invocation_lane_mismatch"


def test_pubmed_primary_artifact_scope_must_match_researcher(tmp_path: Path) -> None:
    def drift_artifact_task(evidence: dict[str, object]) -> None:
        primary = next(
            item
            for item in evidence["artifacts"]
            if item["artifact_id"] == "art_pubmed_response"
        )
        primary["provenance"]["task_id"] = "task_execute"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=drift_artifact_task)

    assert error.value.code == "pubmed_primary_artifact_scope_mismatch"


def test_pubmed_primary_source_scope_must_match_researcher(tmp_path: Path) -> None:
    def drift_source_artifact(evidence: dict[str, object]) -> None:
        pubmed = next(
            item
            for item in evidence["provider_identities"]
            if item["provider"] == "pubmed"
        )
        pubmed["source_refs"][0]["evidence_artifact_id"] = (
            "art_ncbi_provider_sequences"
        )

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=drift_source_artifact)

    assert error.value.code == "pubmed_primary_source_scope_mismatch"


def test_micu_overage_or_breach_cannot_enter_attempt_bundle(tmp_path: Path) -> None:
    breached = _ledger_snapshot(
        charged_tokens=500_000_000,
        attempt_count=2,
    )
    breached["hard_limit_overage_tokens"] = 1
    breached["hard_limit_breach_count"] = 1
    breached["reservation_overage_tokens"] = 1

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(
            tmp_path,
            ledger_before=_ledger_snapshot(),
            ledger_after=breached,
        )

    assert error.value.code == "micu_ledger_budget_invalid"


def test_report_content_tamper_is_detected_from_sealed_bytes(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    report_path = artifact_root / "formal/report.md"
    report_path.write_text("tampered report", encoding="utf-8")

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.identity == "artifact:art_report:content"
        and issue.code == "artifact_content_digest_mismatch"
        for issue in result.issues
    )


def test_scoring_is_recomputed_not_trusted_from_declared_digest(tmp_path: Path) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-wrong-score",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    evidence = _valid_evidence(
        roots.artifact_root,
        attempt_kind="positive",
        clean_world=roots.proof,
    )
    scored_path = roots.artifact_root / "formal/motif-scores.csv"
    scored_path.write_text(
        scored_path.read_text(encoding="utf-8").replace("33.6", "99.9", 1),
        encoding="utf-8",
    )
    payload = build_attempt_bundle(
        attempt_id=roots.attempt_id,
        attempt_kind="positive",
        identity=_identity(),
        clean_world=roots.proof,
        ledger_before=_ledger_snapshot(),
        ledger_after=_ledger_snapshot(charged_tokens=20, attempt_count=2),
        artifact_root=roots.artifact_root,
        evidence=evidence,
    )
    bundle_path = roots.evidence_root / "attempt-bundle.json"
    seal_attempt_bundle(payload, bundle_path)

    result = verify_attempt_bundle(bundle_path, artifact_root=roots.artifact_root)

    assert any(issue.code == "scoring_output_mismatch" for issue in result.issues)


def test_similarity_graph_is_recomputed_from_candidate_and_membership_bytes(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-wrong-graph",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    evidence = _valid_evidence(
        roots.artifact_root,
        attempt_kind="positive",
        clean_world=roots.proof,
    )
    nodes_path = roots.artifact_root / "formal/graph-nodes.csv"
    nodes_path.write_text(
        nodes_path.read_text(encoding="utf-8").replace("1.000000", "0.999999", 1),
        encoding="utf-8",
    )
    payload = build_attempt_bundle(
        attempt_id=roots.attempt_id,
        attempt_kind="positive",
        identity=_identity(),
        clean_world=roots.proof,
        ledger_before=_ledger_snapshot(),
        ledger_after=_ledger_snapshot(charged_tokens=20, attempt_count=2),
        artifact_root=roots.artifact_root,
        evidence=evidence,
    )
    bundle_path = roots.evidence_root / "attempt-bundle.json"
    seal_attempt_bundle(payload, bundle_path)

    result = verify_attempt_bundle(bundle_path, artifact_root=roots.artifact_root)

    assert any(issue.code == "similarity_recompute_failed" for issue in result.issues)


def test_offline_verifier_rejects_non_finite_json_without_crashing(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "attempt-bundle.json"
    bundle_path.write_text('{"payload":{"value":NaN},"bundle_digest":"bad"}\n')

    result = verify_attempt_bundle(bundle_path, artifact_root=tmp_path)

    assert result.passed is False
    assert result.issues[0].code == "bundle_unreadable"


def test_bundle_rejects_artifact_symlink_even_when_target_stays_in_root(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-symlink",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    evidence = _valid_evidence(
        roots.artifact_root,
        attempt_kind="positive",
        clean_world=roots.proof,
    )
    report_path = roots.artifact_root / "formal/report.md"
    actual_path = roots.artifact_root / "formal/report-real.md"
    report_path.replace(actual_path)
    report_path.symlink_to(actual_path.name)

    with pytest.raises(CutoverEvidenceError) as error:
        build_attempt_bundle(
            attempt_id=roots.attempt_id,
            attempt_kind="positive",
            identity=_identity(),
            clean_world=roots.proof,
            ledger_before=_ledger_snapshot(),
            ledger_after=_ledger_snapshot(charged_tokens=20, attempt_count=2),
            artifact_root=roots.artifact_root,
            evidence=evidence,
        )

    assert error.value.code == "artifact_symlink_forbidden"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"api_key": "forbidden"}
            ),
            "public_projection_sensitive_key",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"diagnostic": "/tmp/provider/private.json"}
            ),
            "public_projection_host_path",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"endpoint": "http://127.0.0.1:9000/private"}
            ),
            "public_projection_private_url",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"endpoint": "http://0x7f.0.0.1/private"}
            ),
            "public_projection_private_url",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"endpoint": "https://service.namespace.svc/private"}
            ),
            "public_projection_private_url",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"diagnostic": "/scratch/slurm/job-001/stderr"}
            ),
            "public_projection_host_path",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"diagnostic": "/custom/runner/private.json"}
            ),
            "public_projection_host_path",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"diagnostic": r"{\"path\":\"\/home\/user\/private\"}"}
            ),
            "public_projection_host_path",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"diagnostic": "%2Fhome%2Fuser%2Fprivate"}
            ),
            "public_projection_host_path",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"locator": "s3://private-bucket/object"}
            ),
            "public_projection_private_locator",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {
                    "endpoint": (
                        "https://rest.uniprot.org/uniprotkb/search"
                        "?X-Amz-Signature=deadbeef"
                    )
                }
            ),
            "public_projection_url_query",
        ),
    ],
)
def test_bundle_rejects_secret_and_private_path_projection(
    tmp_path: Path,
    mutation,
    code: str,
) -> None:
    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=mutation)

    assert error.value.code == code


def test_public_safety_verifier_preserves_logical_paths_routes_and_query_free_url() -> (
    None
):
    payload = {
        "workspace": "/workspace/src/probe.py",
        "control_socket": "/openzyme/control.sock",
        "route": "/v3/sessions/sess_001/events?replay=1&after_cursor=0",
        "provider_suffixes": [
            "/provider_parsed/proteins.fasta",
            "/provider_parsed/parsed_hits.csv",
            "/provider_parsed/sequences.fasta",
            "/provider_parsed/metadata.json",
        ],
        "source_locator": "https://rest.uniprot.org/uniprotkb/P12345",
        "public_ipv6_locator": "http://[2001:4860:4860::8888]/status",
        "token_count": 42,
        "tokenUsage": 7,
    }

    assert_public_safe_payload(payload)


@pytest.mark.parametrize(
    "unknown_path",
    (
        "/provider_parsed/private.txt",
        "/provider_parsed/../metadata.json",
        "/home/operator/private.py",
        "/tmp/private.json",
        "prefix)/home/operator/private.py",
        "prefix)/p.name",
    ),
)
def test_public_safety_verifier_rejects_unknown_absolute_path(
    unknown_path: str,
) -> None:
    with pytest.raises(CutoverEvidenceError) as error:
        assert_public_safe_payload({"diagnostic": unknown_path})

    assert error.value.code == "public_projection_host_path"


@pytest.mark.parametrize(
    "private_key",
    (
        "provider_access_token",
        "micu_api_key",
        "provider_client_secret",
        "session_cookie",
        "local_path",
        "private_locator",
        "runner_config",
        "AWS_SECRET_ACCESS_KEY",
        "MYSQL_PWD",
        "REDISCLI_AUTH",
        "AZURE_STORAGE_CONNECTION_STRING",
        "clientSecret",
        "accessToken",
        "refreshToken",
        "privateKey",
        "storageUri",
        "sourceUri",
        "hostPath",
        "remotePath",
        "localPath",
        "runnerConfig",
        "connectionString",
    ),
)
def test_public_safety_verifier_rejects_sensitive_key_aliases(
    private_key: str,
) -> None:
    with pytest.raises(CutoverEvidenceError) as error:
        assert_public_safe_payload({private_key: "opaque"})

    assert error.value.code == "public_projection_sensitive_key"


@pytest.mark.parametrize(
    "private_text",
    (
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "Set-Cookie: session=abc",
        "cookie=sessionid",
        "refresh_token=abc",
        "credential=opaque",
        "private_key=opaque",
        "token=opaque",
        "AWS_SECRET_ACCESS_KEY=opaque",
        "MYSQL_PWD=opaque",
        "REDISCLI_AUTH=opaque",
        "AZURE_STORAGE_CONNECTION_STRING=opaque",
    ),
)
def test_public_safety_verifier_rejects_sensitive_free_text(
    private_text: str,
) -> None:
    with pytest.raises(CutoverEvidenceError) as error:
        assert_public_safe_payload({"diagnostic": private_text})

    assert error.value.code == "public_projection_secret_value"


def test_probe_artifacts_cannot_enter_formal_operation(tmp_path: Path) -> None:
    def contaminate(evidence: dict[str, object]) -> None:
        operation = next(
            item for item in evidence["operations"] if item["operation_id"] == "op_ncbi"
        )
        operation["inputs"] = [
            {
                "artifact_id": "art_probe_ncbi_fasta",
                "content_digest": _digest("probe"),
            }
        ]

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=contaminate)

    assert error.value.code == "probe_data_entered_formal_operation"


def test_known_positive_probe_cannot_pass_from_status_flags_only(
    tmp_path: Path,
) -> None:
    def detach_probe_receipt(evidence: dict[str, object]) -> None:
        evidence["known_positive_probe"]["provider_receipts"][0]["operation_id"] = (
            "op_ncbi"
        )

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=detach_probe_receipt)

    assert error.value.code == "known_positive_probe_receipt_invalid"


def test_known_positive_probe_v2_closes_the_globin_six_operation_dag(
    tmp_path: Path,
) -> None:
    payload, bundle_path, artifact_root = _build_bundle(tmp_path)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed, result.to_dict()
    probe = payload["known_positive_probe"]
    assert probe["schema_id"] == KNOWN_POSITIVE_PROBE_SCHEMA_ID
    assert probe["probe_id"] == KNOWN_POSITIVE_PROBE_ID
    assert probe["operation_roles"] == {
        "ncbi_fetch": "op_probe_ncbi",
        "reference_alignment": "op_probe_mafft",
        "hmm_build": "op_probe_hmmbuild",
        "uniprot_fetch": "op_probe_uniprot",
        "candidate_cluster": "op_probe_cdhit",
        "candidate_alignment": "op_probe_hmmalign",
    }
    assert set(probe["artifact_roles"]) == {
        "source_snapshot",
        "ncbi_raw_response",
        "ncbi_fasta",
        "mafft_alignment",
        "hmm_model",
        "uniprot_raw_response",
        "uniprot_fasta",
        "cdhit_clustered_fasta",
        "cdhit_membership",
        "hmmalign_alignment",
    }
    probe_artifacts = {
        artifact["artifact_id"]: artifact
        for artifact in payload["artifacts"]
        if artifact["scope"] == "probe"
    }
    assert set(probe["artifact_ids"]) == set(probe_artifacts)
    assert len(probe_artifacts) == 10
    operations = {
        operation["operation_id"]: operation
        for operation in payload["operations"]
        if operation["scope"] == "probe"
    }
    assert len(operations) == 6
    for provider_receipt in probe["provider_receipts"]:
        raw_artifact = probe_artifacts[provider_receipt["raw_response_artifact_id"]]
        envelope = json.loads(
            (artifact_root / raw_artifact["relative_path"]).read_text(encoding="utf-8")
        )
        assert envelope["schema_id"] == "provider_raw_http_response_set@1"
        assert envelope["provider"] == provider_receipt["provider"]
        response = envelope["responses"][0]
        raw_body = base64.b64decode(response["body_base64"], validate=True)
        assert response["body_digest"] == _digest_bytes(raw_body)
        assert response["size_bytes"] == len(raw_body)
        assert provider_receipt["response_digest"] == response["body_digest"]
    assert operations["op_probe_ncbi"]["parameters"]["accessions"] == list(
        KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS
    )
    assert operations["op_probe_uniprot"]["parameters"]["accessions"] == list(
        KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS
    )
    cdhit_receipt = next(
        receipt
        for receipt in probe["toolchain_receipts"]
        if receipt["tool"] == "cd-hit"
    )
    assert cdhit_receipt["parameters"] == {"identity": 1.0, "mode": "protein"}
    snapshot = probe_artifacts[probe["artifact_roles"]["source_snapshot"]]
    isolation = probe["isolation"]
    assert snapshot["origin"] == "sandbox_run"
    assert snapshot["provenance"] == {
        **snapshot["provenance"],
        "producer": "sandbox_source_snapshot",
        "sandbox_run_id": isolation["sandbox_run_id"],
        "source_snapshot_digest": isolation["source_snapshot_digest"],
    }
    assert isolation["source_snapshot_artifact_digest"] == snapshot["content_digest"]


@pytest.mark.parametrize("provider", ["ncbi", "uniprot"])
def test_known_positive_probe_rejects_raw_provider_body_digest_tamper(
    tmp_path: Path,
    provider: str,
) -> None:
    artifact_root = tmp_path / "campaign" / "positive-one" / "artifacts"

    def tamper_raw_body(evidence: dict[str, object]) -> None:
        probe = evidence["known_positive_probe"]
        artifact_role = f"{provider}_raw_response"
        artifact_id = probe["artifact_roles"][artifact_role]
        artifact = next(
            item for item in evidence["artifacts"] if item["artifact_id"] == artifact_id
        )
        path = artifact_root / str(artifact["relative_path"])
        envelope = json.loads(path.read_text(encoding="utf-8"))
        body = base64.b64decode(
            envelope["responses"][0]["body_base64"],
            validate=True,
        )
        envelope["responses"][0]["body_base64"] = base64.b64encode(
            body + b"tamper"
        ).decode("ascii")
        path.write_bytes(canonical_json_bytes(envelope) + b"\n")

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=tamper_raw_body)

    assert error.value.code == "known_positive_probe_provider_invalid"


def test_known_positive_probe_rejects_weakened_cdhit_parameters(
    tmp_path: Path,
) -> None:
    def weaken_cdhit(evidence: dict[str, object]) -> None:
        receipt = next(
            item
            for item in evidence["known_positive_probe"]["toolchain_receipts"]
            if item["tool"] == "cd-hit"
        )
        receipt["parameters"] = {"identity": 0.85, "mode": "protein"}

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=weaken_cdhit)

    assert error.value.code == "known_positive_probe_toolchain_invalid"


def test_known_positive_probe_rejects_source_tree_isolation_drift(
    tmp_path: Path,
) -> None:
    def drift_source_tree(evidence: dict[str, object]) -> None:
        evidence["known_positive_probe"]["isolation"]["source_snapshot_digest"] = (
            _digest("different-probe-source-tree")
        )

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=drift_source_tree)

    assert error.value.code == "known_positive_probe_isolation_invalid"


def test_known_positive_probe_rejects_snapshot_sandbox_lineage_tamper(
    tmp_path: Path,
) -> None:
    def detach_snapshot(evidence: dict[str, object]) -> None:
        snapshot_id = evidence["known_positive_probe"]["artifact_roles"][
            "source_snapshot"
        ]
        snapshot = next(
            item for item in evidence["artifacts"] if item["artifact_id"] == snapshot_id
        )
        snapshot["provenance"]["sandbox_run_id"] = "sandbox_run_unbound"

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=detach_snapshot,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "sandbox_source_snapshot_lineage_invalid"
        for issue in result.issues
    )


def test_offline_verifier_recomputes_sandbox_source_tree_envelope(
    tmp_path: Path,
) -> None:
    payload, bundle_path, artifact_root = _build_bundle(tmp_path)
    snapshot = next(
        item
        for item in payload["artifacts"]
        if item["origin"] == "sandbox_run"
    )
    snapshot_path = artifact_root / str(snapshot["relative_path"])
    source_envelope = json.loads(snapshot_path.read_bytes())
    tampered_content = b"# tampered but externally re-sealed\n"
    source_envelope["files"][0].update(
        {
            "content_base64": base64.b64encode(tampered_content).decode("ascii"),
            "content_digest": _digest_bytes(tampered_content),
            "size_bytes": len(tampered_content),
        }
    )
    source_envelope["source_tree_digest"] = canonical_digest(
        [
            {
                "relative_path": source_envelope["files"][0]["relative_path"],
                "content_digest": _digest_bytes(tampered_content),
                "size_bytes": len(tampered_content),
            }
        ]
    )
    tampered_bytes = canonical_json_bytes(source_envelope) + b"\n"
    snapshot_path.write_bytes(tampered_bytes)

    def reseal_outer_envelope(bundle: dict[str, object]) -> None:
        payload_record = next(
            item
            for item in bundle["payload"]["artifacts"]
            if item["artifact_id"] == snapshot["artifact_id"]
        )
        payload_record["content_digest"] = _digest_bytes(tampered_bytes)
        payload_record["size_bytes"] = len(tampered_bytes)
        bundle["bundle_digest"] = canonical_digest(bundle["payload"])

    _rewrite_envelope(bundle_path, reseal_outer_envelope)
    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "sealed_source_tree_digest_mismatch"
        and issue.identity
        == f"artifact:{snapshot['artifact_id']}:source_tree"
        for issue in result.issues
    )


def test_offline_verifier_scans_decoded_source_after_outer_reseal(
    tmp_path: Path,
) -> None:
    payload, bundle_path, artifact_root = _build_bundle(tmp_path)
    snapshot = next(
        item for item in payload["artifacts"] if item["origin"] == "sandbox_run"
    )
    snapshot_path = artifact_root / str(snapshot["relative_path"])
    source_envelope = json.loads(snapshot_path.read_bytes())
    private_source = b"SOURCE = '/home/operator/private.py'\n"
    source_envelope["files"][0].update(
        {
            "content_base64": base64.b64encode(private_source).decode("ascii"),
            "content_digest": _digest_bytes(private_source),
            "size_bytes": len(private_source),
        }
    )
    tree_digest = _source_tree_digest(
        {str(source_envelope["files"][0]["relative_path"]): private_source}
    )
    source_envelope["source_tree_digest"] = tree_digest
    tampered_bytes = canonical_json_bytes(source_envelope) + b"\n"
    snapshot_path.write_bytes(tampered_bytes)

    def reseal_outer_envelope(bundle: dict[str, object]) -> None:
        record = next(
            item
            for item in bundle["payload"]["artifacts"]
            if item["artifact_id"] == snapshot["artifact_id"]
        )
        record["content_digest"] = _digest_bytes(tampered_bytes)
        record["size_bytes"] = len(tampered_bytes)
        record["provenance"]["source_snapshot_digest"] = tree_digest
        record["provenance_digest"] = canonical_digest(record["provenance"])
        bundle["bundle_digest"] = canonical_digest(bundle["payload"])

    _rewrite_envelope(bundle_path, reseal_outer_envelope)
    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "public_projection_host_path"
        for issue in result.issues
    )


def test_offline_verifier_rejects_source_snapshot_kind_drift(
    tmp_path: Path,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    def drift_kind(bundle: dict[str, object]) -> None:
        snapshot = next(
            item
            for item in bundle["payload"]["artifacts"]
            if item["origin"] == "sandbox_run"
        )
        snapshot["kind"] = "result"
        bundle["bundle_digest"] = canonical_digest(bundle["payload"])

    _rewrite_envelope(bundle_path, drift_kind)
    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "sealed_source_tree_kind_invalid" for issue in result.issues
    )


def test_required_aox_dag_rejects_missing_digest_edge(tmp_path: Path) -> None:
    def remove_hmm_input(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_hmmbuild"
        )
        operation["inputs"] = []
        _refresh_operation_identity(operation)

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=remove_hmm_input,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "aox_operation_dag_edge_missing" for issue in result.issues
    )


def test_uniprot_source_cannot_bind_post_uniprot_filtered_hits(
    tmp_path: Path,
) -> None:
    payload, _, artifact_root = _build_bundle(tmp_path)
    operations = {item["operation_id"]: item for item in payload["operations"]}
    post_filter_output = next(
        dict(item)
        for item in operations["op_post_uniprot_filter"]["outputs"]
        if item["artifact_id"] == "art_post_uniprot_filtered_hits"
    )
    uniprot_operation = operations["op_uniprot"]
    uniprot_operation["inputs"] = [post_filter_output]
    uniprot_operation["parameters"] = {
        **dict(uniprot_operation["parameters"]),
        "source_hit_artifact": post_filter_output,
    }
    _refresh_operation_identity(uniprot_operation)
    uniprot_operation["record_digest"] = canonical_digest(
        {
            key: value
            for key, value in uniprot_operation.items()
            if key != "record_digest"
        }
    )
    cyclic_bundle_path = tmp_path / "cyclic-attempt-bundle.json"
    seal_attempt_bundle(payload, cyclic_bundle_path)

    result = verify_attempt_bundle(
        cyclic_bundle_path,
        artifact_root=artifact_root,
    )

    assert any(
        issue.code == "aox_provider_dependency_invalid" for issue in result.issues
    )


def test_hmmer_upstream_empty_is_accepted_only_from_recomputed_artifacts(
    tmp_path: Path,
) -> None:
    payload, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        scientific_branch="hmmer_upstream_empty",
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is True
    operations = {item["operation_id"]: item for item in payload["operations"]}
    assert "op_uniprot" not in operations
    assert "op_hmmalign" not in operations
    assert "op_cdhit" not in operations
    assert {
        "op_pre_uniprot_score_filter",
        "op_upstream_empty_materialization",
        "op_empty_target_scoring",
        "op_empty_membership",
    }.issubset(operations)
    chain = payload["scientific_checks"]["aox_chain"]
    assert chain["operation_roles"]["empty_target_scoring_materialization"] == (
        "op_empty_target_scoring"
    )
    artifact_by_id = {
        artifact["artifact_id"]: artifact for artifact in payload["artifacts"]
    }

    def artifact_bytes(role: str) -> bytes:
        artifact = artifact_by_id[chain["artifact_roles"][role]]
        return (artifact_root / artifact["relative_path"]).read_bytes()

    assert artifact_bytes("scoring_input") == artifact_bytes("scoring_reference")
    assert artifact_bytes("scoring_alignment") == artifact_bytes("scoring_reference")
    assert operations["op_scoring_input_assembly"]["parameters"]["target_count"] == 0
    uniprot = next(
        item for item in payload["provider_identities"] if item["provider"] == "uniprot"
    )
    assert uniprot == {
        **uniprot,
        "status": "upstream_empty",
        "canonical_ref_kind": "upstream_empty",
        "operation_id": None,
        "invocation_id": None,
        "request_digest": None,
        "response_digest": None,
        "provider_io_performed": False,
        "cache_consulted": False,
    }
    receipt_artifact = next(
        item
        for item in payload["artifacts"]
        if item["artifact_id"] == "art_uniprot_upstream_empty"
    )
    receipt_payload = json.loads(
        (artifact_root / receipt_artifact["relative_path"]).read_text(encoding="utf-8")
    )
    assert receipt_payload["schema_id"] == "provider_upstream_empty_receipt@1"
    assert "request_digest" not in receipt_payload
    assert "response_digest" not in receipt_payload
    for role in ("target_sequences", "candidates"):
        artifact = artifact_by_id[chain["artifact_roles"][role]]
        receipt = artifact["registration_validation"]
        assert receipt == {
            **receipt,
            "schema_id": "openzyme_typed_empty_artifact_validation@1",
            "kind": "sequence",
            "format": "fasta",
            "validation_profile": "fasta_zero_records@1",
            "empty_result_reason": "no_hmmer_hits",
        }


def test_offline_verifier_rejects_missing_typed_empty_registration_receipt(
    tmp_path: Path,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        scientific_branch="hmmer_upstream_empty",
    )

    def remove_receipt(bundle: dict[str, object]) -> None:
        artifact = next(
            item
            for item in bundle["payload"]["artifacts"]
            if item["artifact_id"] == "art_target_sequences"
        )
        artifact.pop("registration_validation")
        bundle["bundle_digest"] = canonical_digest(bundle["payload"])

    _rewrite_envelope(bundle_path, remove_receipt)
    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "typed_empty_artifact_validation_invalid"
        and issue.identity
        == "artifact:art_target_sequences:registration_validation"
        for issue in result.issues
    )


def test_self_claimed_hmmer_empty_cannot_override_nonempty_derived_accessions(
    tmp_path: Path,
) -> None:
    def forge_empty_claim(evidence: dict[str, object]) -> None:
        chain = evidence["scientific_checks"]["aox_chain"]
        dependency = chain["provider_dependencies"][0]
        chain["empty_branch"] = {
            "schema_id": "aox_empty_branch@1",
            "stage": "pre_uniprot_score_filter",
            "reason": "no_filtered_hmmer_accessions",
            "trigger_artifact_id": dependency["derived_accession_artifact_id"],
            "trigger_artifact_digest": dependency["derived_accession_artifact_digest"],
            "observed_count_before": 2,
            "observed_count_after": 0,
            "derivation_operation_id": dependency["derivation_operation_id"],
            "skip_provider_record_id": "provider_record_uniprot",
            "omitted_controlled_roles": [],
            "empty_materialization_operation_id": None,
            "empty_membership_operation_id": None,
        }
        evidence["scientific_outcome"] = {
            "status": "empty",
            "candidate_count": 0,
            "empty_result_reason": "no_filtered_hmmer_accessions",
            "cutover_eligible": True,
        }

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=forge_empty_claim,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code
        in {
            "aox_empty_branch_invalid",
            "aox_operation_dag_schema_invalid",
            "scientific_outcome_artifact_mismatch",
        }
        for issue in result.issues
    )


@pytest.mark.parametrize("digest_field", ["request_digest", "response_digest"])
def test_upstream_empty_provider_receipt_rejects_fake_io_digests(
    tmp_path: Path,
    digest_field: str,
) -> None:
    def add_fake_io_digest(evidence: dict[str, object]) -> None:
        provider = next(
            item
            for item in evidence["provider_identities"]
            if item["provider"] == "uniprot"
        )
        provider[digest_field] = _digest(f"fake-{digest_field}")

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(
            tmp_path,
            scientific_branch="hmmer_upstream_empty",
            mutate_evidence=add_fake_io_digest,
        )

    assert error.value.code == "provider_receipt_invalid"


@pytest.mark.parametrize("tamper_target", ["provider", "dependency"])
def test_upstream_empty_provider_receipt_rejects_tampered_skip_digest(
    tmp_path: Path,
    tamper_target: str,
) -> None:
    def tamper_skip_digest(evidence: dict[str, object]) -> None:
        if tamper_target == "provider":
            provider = next(
                item
                for item in evidence["provider_identities"]
                if item["provider"] == "uniprot"
            )
            provider["skip_receipt_digest"] = _digest("tampered-provider-skip")
        else:
            dependency = evidence["scientific_checks"]["aox_chain"][
                "provider_dependencies"
            ][0]
            dependency["skip_receipt_digest"] = _digest("tampered-dependency-skip")

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(
            tmp_path,
            scientific_branch="hmmer_upstream_empty",
            mutate_evidence=tamper_skip_digest,
        )

    assert error.value.code == "provider_receipt_invalid"


def test_sequence_join_rejects_uniprot_mapping_tamper(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    metadata_path = artifact_root / "formal/provider/uniprot-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["records"][0]["mapping_annotations"][0]["target_accession"] = "Q9ZZZ9"
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "sequence_join_recompute_failed" for issue in result.issues
    )


def test_sequence_join_rejects_final_join_output_tamper(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    joined_hits_path = artifact_root / "formal/calculation/hits-len650-700-200.csv"
    joined_hits_path.write_bytes(joined_hits_path.read_bytes() + b"tampered\n")

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(issue.code == "sequence_join_output_mismatch" for issue in result.issues)


def test_required_aox_dag_rejects_failed_critical_operation(tmp_path: Path) -> None:
    def fail_hmm_build(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_hmmbuild"
        )
        operation["status"] = "failed"

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=fail_hmm_build,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "aox_required_operation_not_completed" for issue in result.issues
    )


def test_approval_cannot_be_reused_after_operation_inputs_change(
    tmp_path: Path,
) -> None:
    def change_approved_operation(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_hmmbuild"
        )
        operation["parameters"] = {"threshold_tenths": 59}
        _refresh_operation_identity(operation)

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=change_approved_operation,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "approval_operation_identity_mismatch" for issue in result.issues
    )


def test_approval_cannot_be_reused_after_operation_route_changes(
    tmp_path: Path,
) -> None:
    def change_approved_route(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_hmmbuild"
        )
        operation["route_reason"] = "tampered_operator_route"
        _refresh_operation_identity(operation)

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=change_approved_route,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "approval_operation_identity_mismatch" for issue in result.issues
    )


def test_provider_backend_run_must_match_invocation_receipt(tmp_path: Path) -> None:
    def replace_backend_run(evidence: dict[str, object]) -> None:
        operation = next(
            item for item in evidence["operations"] if item["operation_id"] == "op_ncbi"
        )
        operation["backend_run_id"] = "different_invocation"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=replace_backend_run)

    assert error.value.code == "provider_operation_receipt_mismatch"


def test_tool_backend_run_must_match_hpc_job_receipt(tmp_path: Path) -> None:
    def replace_backend_run(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_align"
        )
        operation["backend_run_id"] = "different_job"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=replace_backend_run)

    assert error.value.code == "toolchain_operation_receipt_mismatch"


def test_scientific_outcome_must_match_candidate_and_graph_artifacts(
    tmp_path: Path,
) -> None:
    def contradict_candidate_count(evidence: dict[str, object]) -> None:
        evidence["scientific_outcome"]["candidate_count"] = 0
        evidence["scientific_outcome"]["status"] = "empty"
        evidence["scientific_outcome"]["empty_result_reason"] = "no_candidates"

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=contradict_candidate_count,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "scientific_outcome_artifact_mismatch" for issue in result.issues
    )


def test_positive_micu_delta_must_belong_to_aox_scenario(tmp_path: Path) -> None:
    before = _ledger_snapshot()
    after = _ledger_snapshot(charged_tokens=20, attempt_count=2)
    before["by_scenario"][0]["scenario"] = "unrelated_live_test"
    after["by_scenario"][0]["scenario"] = "unrelated_live_test"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(
            tmp_path,
            ledger_before=before,
            ledger_after=after,
        )

    assert error.value.code == "micu_usage_unattributed"


def test_fault_micu_delta_must_belong_to_aox_scenario(tmp_path: Path) -> None:
    before = _ledger_snapshot()
    after = _ledger_snapshot(charged_tokens=20, attempt_count=2)
    before["by_scenario"][0]["scenario"] = "unrelated_live_test"
    after["by_scenario"][0]["scenario"] = "unrelated_live_test"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(
            tmp_path,
            attempt_kind="fault",
            ledger_before=before,
            ledger_after=after,
        )

    assert error.value.code == "micu_usage_unattributed"


def test_micu_group_totals_cannot_contradict_snapshot(tmp_path: Path) -> None:
    after = _ledger_snapshot(charged_tokens=20, attempt_count=2)
    after["by_model"][0]["charged_tokens"] = 19

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, ledger_after=after)

    assert error.value.code == "micu_ledger_group_invalid"


def test_fault_source_must_be_bound_to_completed_provider_receipt(
    tmp_path: Path,
) -> None:
    def detach_provider_artifact(evidence: dict[str, object]) -> None:
        provider = next(
            item
            for item in evidence["provider_identities"]
            if item["provider"] == "ncbi"
        )
        provider["artifact_ids"] = []

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
        mutate_evidence=detach_provider_artifact,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "fault_operation_attestation_invalid" for issue in result.issues
    )


def test_product_receipt_bytes_are_parsed_and_bound_offline(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    receipt_path = artifact_root / "formal/attestation/workspace-projection.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["session_id"] = "sess_unbound"
    receipt_path.write_bytes(canonical_json_bytes(receipt) + b"\n")

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(issue.code == "product_receipt_mismatch" for issue in result.issues)


@pytest.mark.parametrize(
    ("approval_mode", "expected_decision", "expected_record_count"),
    (("chrome-once", "GO", 3), ("auto", "NO-GO", 2)),
)
def test_campaign_derives_go_only_with_required_chrome_proof(
    tmp_path: Path,
    approval_mode: str,
    expected_decision: str,
    expected_record_count: int,
) -> None:
    ledger_path = tmp_path / "persistent-ledger.sqlite3"
    ledger = LiveMicuTokenLedger(ledger_path, hard_limit_tokens=500_000_000)
    ledger_identity = safe_micu_ledger_snapshot(ledger_path)["ledger_identity_digest"]
    campaign_config = _effective_config(str(ledger_identity))
    if approval_mode == "chrome-once":
        campaign_config["driver"]["approval_mode"] = "chrome-once"
        campaign_config["driver"]["ui_dist_digest"] = _digest("ui-dist")
    campaign_identity = _identity(str(ledger_identity))
    campaign_identity["config_digest"] = canonical_digest(campaign_config)
    invocation_count = 0

    def charge_micu() -> None:
        nonlocal invocation_count
        invocation_count += 1
        reservation = ledger.reserve_attempt(
            scenario="aox_blank_world_cutover",
            purpose="positive_e2e",
            kind="tool_calling",
            model="micu-live",
            attempt=invocation_count,
            estimated_input_tokens=2,
            reserved_output_tokens=2,
        )
        ledger.reconcile_success(
            reservation,
            {"input_tokens": 2, "output_tokens": 2},
        )

    def positive_runner(context):
        charge_micu()
        evidence = _valid_evidence(
            context.roots.artifact_root,
            attempt_kind="positive",
            clean_world=context.roots.proof,
            run_suffix=context.roots.attempt_id,
            effective_config=campaign_config,
        )
        if approval_mode == "chrome-once" and context.attempt_number == 1:
            browser_receipt = _browser_approval_receipt(evidence)
            _attach_browser_receipt_artifacts(
                evidence,
                artifact_root=context.roots.artifact_root,
                browser_receipt=browser_receipt,
            )
        launch = evidence["product_path"]["launch_receipt"]
        launch["campaign_attempt_number"] = context.attempt_number
        launch["approval_mode"] = approval_mode
        if not (approval_mode == "chrome-once" and context.attempt_number == 1):
            launch["browser_approval_receipt"] = None
            launch["browser_observation_receipt"] = None
        return evidence

    def fault_runner(context):
        charge_micu()
        evidence = _valid_evidence(
            context.roots.artifact_root,
            attempt_kind="fault",
            clean_world=context.roots.proof,
            run_suffix=context.roots.attempt_id,
            effective_config=campaign_config,
        )
        launch = evidence["product_path"]["launch_receipt"]
        launch["campaign_attempt_number"] = context.attempt_number
        launch["approval_mode"] = approval_mode
        launch["browser_approval_receipt"] = None
        launch["browser_observation_receipt"] = None
        return evidence

    campaign = AoxCutoverCampaign(
        campaign_root=tmp_path / "campaign",
        identity=campaign_identity,
        ledger_path=ledger_path,
        positive_runner=positive_runner,
        fault_runner=fault_runner,
        allowed_prerequisites=_allowed_prerequisites(campaign_identity),
    )

    records, decision = campaign.run()

    assert len(records) == expected_record_count
    assert all(record.verification.passed for record in records)
    assert (
        len({record.artifact_root.parent.name for record in records})
        == expected_record_count
    )
    assert decision["decision"] == expected_decision
    assert decision["attempt_digests"] == [record.bundle_digest for record in records]
    assert decision["decision_digest"] == canonical_digest(
        {key: value for key, value in decision.items() if key != "decision_digest"}
    )
    if approval_mode == "auto":
        assert decision["blocker"]["code"] == "fault_launch_attestation_invalid"


def test_campaign_rejects_reused_positive_runtime_receipts(tmp_path: Path) -> None:
    ledger_path = tmp_path / "persistent-ledger.sqlite3"
    ledger = LiveMicuTokenLedger(ledger_path, hard_limit_tokens=500_000_000)
    ledger_identity = safe_micu_ledger_snapshot(ledger_path)["ledger_identity_digest"]
    campaign_config = _effective_config(str(ledger_identity))
    campaign_config["driver"]["approval_mode"] = "chrome-once"
    campaign_config["driver"]["ui_dist_digest"] = _digest("ui-dist")
    campaign_identity = _identity(str(ledger_identity))
    campaign_identity["config_digest"] = canonical_digest(campaign_config)
    invocation_count = 0

    def charge_micu() -> None:
        nonlocal invocation_count
        invocation_count += 1
        reservation = ledger.reserve_attempt(
            scenario="aox_blank_world_cutover",
            purpose="positive_e2e",
            kind="tool_calling",
            model="micu-live",
            attempt=invocation_count,
            estimated_input_tokens=1,
            reserved_output_tokens=1,
        )
        ledger.reconcile_success(
            reservation,
            {"input_tokens": 1, "output_tokens": 1},
        )

    def positive_runner(context):
        charge_micu()
        evidence = _valid_evidence(
            context.roots.artifact_root,
            attempt_kind="positive",
            clean_world=context.roots.proof,
            effective_config=campaign_config,
        )
        if context.attempt_number == 1:
            browser_receipt = _browser_approval_receipt(evidence)
            _attach_browser_receipt_artifacts(
                evidence,
                artifact_root=context.roots.artifact_root,
                browser_receipt=browser_receipt,
            )
        launch = evidence["product_path"]["launch_receipt"]
        launch["campaign_attempt_number"] = context.attempt_number
        launch["approval_mode"] = "chrome-once"
        if context.attempt_number != 1:
            launch["browser_approval_receipt"] = None
            launch["browser_observation_receipt"] = None
        return evidence

    def fault_runner(context):
        charge_micu()
        evidence = _valid_evidence(
            context.roots.artifact_root,
            attempt_kind="fault",
            clean_world=context.roots.proof,
            run_suffix=context.roots.attempt_id,
            effective_config=campaign_config,
        )
        launch = evidence["product_path"]["launch_receipt"]
        launch["campaign_attempt_number"] = context.attempt_number
        launch["approval_mode"] = "chrome-once"
        launch["browser_approval_receipt"] = None
        launch["browser_observation_receipt"] = None
        return evidence

    campaign = AoxCutoverCampaign(
        campaign_root=tmp_path / "campaign",
        identity=campaign_identity,
        ledger_path=ledger_path,
        positive_runner=positive_runner,
        fault_runner=fault_runner,
        allowed_prerequisites=_allowed_prerequisites(campaign_identity),
    )

    records, decision = campaign.run()

    assert len(records) == 3
    assert all(record.verification.passed for record in records)
    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "campaign_positive_not_independent"


def test_campaign_launch_guard_fails_before_attempt_roots_or_runner_call(
    tmp_path: Path,
) -> None:
    campaign_root = tmp_path / "campaign"
    guard_calls = 0
    runner_calls = 0

    def launch_guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        raise AoxCutoverLaunchError(
            "aox_launch_snapshot_drift",
            "private launch detail must not enter sealed evidence",
        )

    def runner(context):
        nonlocal runner_calls
        runner_calls += 1
        raise AssertionError(f"runner must not receive {context!r}")

    campaign = AoxCutoverCampaign(
        campaign_root=campaign_root,
        identity=_identity(),
        ledger_path=tmp_path / "persistent-ledger.sqlite3",
        positive_runner=runner,
        fault_runner=runner,
        allowed_prerequisites=_allowed_prerequisites(),
        launch_guard=launch_guard,
    )

    records, decision = campaign.run()

    assert records == ()
    assert guard_calls == 1
    assert runner_calls == 0
    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "aox_launch_snapshot_drift"
    assert not (tmp_path / "persistent-ledger.sqlite3").exists()
    assert campaign_root.is_dir()
    assert all(not path.is_dir() for path in campaign_root.iterdir())
    failure = json.loads(
        (campaign_root / "campaign-driver-failure.json").read_text(encoding="utf-8")
    )
    assert failure["payload"]["failure_code"] == "aox_launch_snapshot_drift"
    assert "private launch detail" not in json.dumps(failure, sort_keys=True)


def test_fault_runner_exception_is_sealed_and_campaign_stays_no_go(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "persistent-ledger.sqlite3"
    ledger = LiveMicuTokenLedger(ledger_path, hard_limit_tokens=500_000_000)
    ledger_identity = safe_micu_ledger_snapshot(ledger_path)["ledger_identity_digest"]
    campaign_identity = _identity(str(ledger_identity))
    campaign_config = _effective_config(str(ledger_identity))
    invocation_count = 0

    def positive_runner(context):
        nonlocal invocation_count
        invocation_count += 1
        reservation = ledger.reserve_attempt(
            scenario="aox_blank_world_cutover",
            purpose="positive_e2e",
            kind="tool_calling",
            model="micu-live",
            attempt=invocation_count,
            estimated_input_tokens=1,
            reserved_output_tokens=1,
        )
        ledger.reconcile_success(
            reservation,
            {"input_tokens": 1, "output_tokens": 1},
        )
        return _valid_evidence(
            context.roots.artifact_root,
            attempt_kind="positive",
            clean_world=context.roots.proof,
            run_suffix=context.roots.attempt_id,
            effective_config=campaign_config,
        )

    def fault_runner(context):
        del context
        raise RuntimeError("private fault runner detail")

    campaign = AoxCutoverCampaign(
        campaign_root=tmp_path / "campaign",
        identity=campaign_identity,
        ledger_path=ledger_path,
        positive_runner=positive_runner,
        fault_runner=fault_runner,
        allowed_prerequisites=_allowed_prerequisites(campaign_identity),
    )

    records, decision = campaign.run()

    assert len(records) == 3
    assert records[-1].verification.passed is True
    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "fault_not_fail_closed"


def test_campaign_remains_no_go_for_missing_or_unverified_attempt() -> None:
    failed = AttemptRunRecord(
        attempt_id="positive-failed",
        attempt_kind="positive",
        bundle_path=Path("missing.json"),
        artifact_root=Path("missing-artifacts"),
        bundle_digest=_digest("failed"),
        verification=VerificationResult(
            passed=False,
            bundle_digest=_digest("failed"),
            attempt_id="positive-failed",
            attempt_kind="positive",
            issues=(),
        ),
    )

    decision = evaluate_campaign([failed], decided_at="2026-07-17T00:00:00+00:00")

    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "attempt_verification_failed"


def test_campaign_runner_failure_is_sealed_as_safe_no_go_evidence(
    tmp_path: Path,
) -> None:
    def failing_runner(context):
        del context
        raise RuntimeError("private /tmp/detail and api_key=must-not-project")

    campaign = AoxCutoverCampaign(
        campaign_root=tmp_path / "campaign",
        identity=_identity(),
        ledger_path=tmp_path / "persistent-ledger.sqlite3",
        positive_runner=failing_runner,
        fault_runner=failing_runner,
        allowed_prerequisites=_allowed_prerequisites(),
    )

    records, decision = campaign.run()

    assert len(records) == 1
    assert records[0].verification.passed is True
    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "campaign_runner_failed"
    serialized = records[0].bundle_path.read_text(encoding="utf-8")
    assert "must-not-project" not in serialized
    assert str(tmp_path) not in serialized


def test_campaign_decision_is_digest_checked_and_append_only(tmp_path: Path) -> None:
    decision = evaluate_campaign([], decided_at="2026-07-17T00:00:00+00:00")
    destination = tmp_path / "campaign-decision.json"

    digest = seal_campaign_decision(decision, destination)

    assert digest == decision["decision_digest"]
    assert destination.stat().st_mode & 0o222 == 0
    with pytest.raises(CutoverEvidenceError) as error:
        seal_campaign_decision(decision, destination)
    assert error.value.code == "campaign_decision_append_only"


def test_cli_decide_returns_structured_no_go_for_unreadable_bundle(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = cutover_cli_main(
        [
            "decide",
            "--attempt",
            str(tmp_path / "missing-bundle.json"),
            str(tmp_path / "missing-artifacts"),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert output["decision"] == "NO-GO"
    assert output["blocker"]["code"] == "attempt_verification_failed"
