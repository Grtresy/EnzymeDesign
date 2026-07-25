from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from openzyme_core import MutationScopeService
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import TaskBoardService
from openzyme_core import TaskFinishCommand
from openzyme_domain import MutationWriterKind
from openzyme_domain import TaskStatus
from openzyme_host_api.aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_MICU_BINDING_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID,
)
from openzyme_host_api.aox_closure_stage_authority import (
    build_aox_closure_stage_authority_plan,
)
from openzyme_host_api.aox_closure_stage_authority import (
    closure_stage_authority_consumption_path,
)
from openzyme_host_api.aox_closure_stage_authority import (
    consume_aox_closure_stage_authority_plan,
)
from openzyme_host_api.aox_closure_stage_authority import (
    publish_aox_closure_stage_authority_plan,
)
from openzyme_host_api.aox_closure_stage_reconstruction import (
    independently_verify_aox_closure_stage_reconstruction,
)
from openzyme_host_api.aox_closure_stage_reconstruction import (
    reconstruct_aox_closure_stage,
)
from openzyme_host_api.aox_closure_stage_reconstruction import (
    validate_aox_closure_stage_reconstruction_receipt,
)
from openzyme_host_api.aox_closure_stage_live import _runtime_projection
from openzyme_host_api.aox_closure_stage_source import (
    independently_verify_aox_closure_stage_source_manifest,
)
from openzyme_host_api.aox_closure_stage_source import (
    qualify_aox_closure_stage_source,
)
from openzyme_host_api.aox_closure_stage_source import (
    resolve_aox_closure_stage_source_inventory,
)
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_ID,
)


_R59_CAMPAIGN_ROOT = Path(
    "/tmp/openzyme-aox-cutover/"
    "r59-aox_campaign_43f2726e7fad2738b135abd1"
)
_R59_AUTHORITY_ROOT = Path(
    "/tmp/openzyme-aox-authority/r59-431e2c5-codex-01"
)
_R59_ATTEMPT_ID = "positive-c3c2c4cc13a367fb54eec84505a61742"
_R59_CAMPAIGN_ID = "aox_campaign_43f2726e7fad2738b135abd1"
_R59_SESSION_ID = (
    "sess_formal_positive_c3c2c4cc13a367fb54eec84505a61742"
)
_R59_EXECUTION_TASK_ID = (
    "aox_execution_cutover_positive_c3c2c4cc13a367fb54eec84505a61742"
)
_R59_EXECUTOR_ID = "agent:executor:805a9b201353"
_R59_SELECTION_ID = "selection_090ab4b6c30e4839d60dd664"
_R59_UNIVERSE_DIGEST = (
    "sha256:f131d838c00f88d55e26c142627153fb"
    "2a7c7d0f03ea69bae4d6b4f87223cb55"
)
_CURRENT_WORKFLOW_REF = (
    "workflow:aox-hmm-live@2.0.0#"
    "sha256:a34878a922536f429acb7ebef52e303610"
    "df184fcc16acf4dce894704321b313"
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _r59_available() -> bool:
    return (
        (_R59_CAMPAIGN_ROOT / _R59_ATTEMPT_ID / "control-plane.sqlite3").is_file()
        and (_R59_AUTHORITY_ROOT / "attempt-authority.json").is_file()
        and (
            _R59_AUTHORITY_ROOT
            / "attempt-authority.json.consumed.json"
        ).is_file()
    )


@pytest.mark.integration
@pytest.mark.skipif(
    not _r59_available(),
    reason="frozen local r59 source evidence is unavailable",
)
def test_repository_backed_r59_cut_reconstructs_into_fresh_isolated_root(
    tmp_path: Path,
) -> None:
    source_inventory = resolve_aox_closure_stage_source_inventory(
        campaign_root=_R59_CAMPAIGN_ROOT,
        attempt_id=_R59_ATTEMPT_ID,
        campaign_id=_R59_CAMPAIGN_ID,
        session_id=_R59_SESSION_ID,
        execution_task_id=_R59_EXECUTION_TASK_ID,
        executor_agent_id=_R59_EXECUTOR_ID,
        selection_id=_R59_SELECTION_ID,
        operation_universe_digest=_R59_UNIVERSE_DIGEST,
        authority_plan_path=(
            _R59_AUTHORITY_ROOT / "attempt-authority.json"
        ),
        authority_consumption_path=(
            _R59_AUTHORITY_ROOT
            / "attempt-authority.json.consumed.json"
        ),
    )
    source_database = Path(str(source_inventory["database_path"]))
    source_database_before = _file_digest(source_database)
    source_wal = Path(str(source_database) + "-wal")
    source_wal_before = (
        source_wal.is_file(),
        source_wal.stat().st_size if source_wal.is_file() else None,
    )
    identity = {
        "git_commit": "a" * 40,
        "config_digest": _digest("1"),
        "workflow_ref": _CURRENT_WORKFLOW_REF,
    }
    prerequisites = {
        "provider_cache_mode": "bypass",
        "evidence_cache_reuse": False,
    }
    qualification = {
        "schema_id": "aox_architecture_qualification_receipt@1",
        "report_payload_digest": _digest("2"),
    }
    qualification_digest = canonical_digest(qualification)
    ledger_path = tmp_path / "micu-ledger.sqlite3"
    ledger_path.write_bytes(b"test-ledger")
    target_parent = tmp_path / "targets"
    target_parent.mkdir()
    contract_bindings = {
        "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
        "workflow_contract_digest": (
            AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
        ),
        "sop_digest": _digest("3"),
        "closure_stage_sop_digest": canonical_digest(
            {"label": "closure-stage-sop"}
        ),
        "architecture_qualification_digest": qualification_digest,
        "ui_dist_digest": _digest("4"),
        "source_launch_receipt_digest": _digest("5"),
        "repair_commit": identity["git_commit"],
        "runtime_config_digest": identity["config_digest"],
    }
    runtime_parity = {
        "schema_id": (
            AOX_CLOSURE_STAGE_RUNTIME_PARITY_DECLARATION_SCHEMA_ID
        ),
        "source_launch_receipt_digest": _digest("5"),
        "model_config_digest": _digest("6"),
        "driver_limits_digest": _digest("7"),
        "writer_policy_digest": _digest("8"),
        "tool_response_policy_digest": _digest("9"),
        "supervision_contract_digest": _digest("a"),
        "public_observation_contract_digest": _digest("b"),
    }
    micu = {
        "schema_id": AOX_CLOSURE_STAGE_MICU_BINDING_SCHEMA_ID,
        "provider": "openai-compatible",
        "endpoint_identity": _digest("c"),
        "model": "gpt-5.5",
        "token_scenario": "aox_closure_stage_diagnostic",
        "ledger_path": str(ledger_path.resolve()),
        "ledger_identity": _digest("d"),
        "effective_config_digest": identity["config_digest"],
    }
    plan = build_aox_closure_stage_authority_plan(
        source_inventory=source_inventory,
        target_parent=target_parent,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        contract_bindings=contract_bindings,
        runtime_parity=runtime_parity,
        micu=micu,
        browser_observation_receipt=None,
        issued_at="2026-07-23T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu=100_000,
        max_cost_microunits=100_000,
        max_wall_time_seconds=3_600,
    )
    authority_path = tmp_path / "closure-stage-authority.json"
    publish_aox_closure_stage_authority_plan(plan, authority_path)
    consumption = consume_aox_closure_stage_authority_plan(
        plan,
        plan_path=authority_path,
        path=closure_stage_authority_consumption_path(authority_path),
    )
    manifest = qualify_aox_closure_stage_source(
        source_inventory=source_inventory,
        diagnostic_id=str(plan["diagnostic_id"]),
    )
    assert (
        independently_verify_aox_closure_stage_source_manifest(manifest)
        == manifest
    )

    reconstruction = reconstruct_aox_closure_stage(
        plan=plan,
        consumption=consumption,
        source_manifest=manifest,
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
    )

    assert _file_digest(source_database) == source_database_before
    assert (
        source_wal.is_file(),
        source_wal.stat().st_size if source_wal.is_file() else None,
    ) == source_wal_before
    assert reconstruction.roots.attempt_root.is_relative_to(
        Path(str(plan["target_root"]))
    )
    assert reconstruction.receipt["acceptance_eligible"] is False
    assert reconstruction.receipt["retained_identities"][
        "formal_adoption_eligible"
    ] is False
    assert set(reconstruction.receipt["exclusions"].values()) == {0}
    assert reconstruction.receipt["canonical_state"]["readiness"][
        "closure_request_ready"
    ] is True
    assert len(
        reconstruction.receipt["canonical_state"]["pending_signals"]
    ) == 1
    for byte_copy in reconstruction.receipt["byte_copies"]:
        source_path = Path(str(byte_copy["source_path"]))
        destination_path = Path(str(byte_copy["destination_path"]))
        assert source_path.is_relative_to(
            Path(str(source_inventory["attempt_root"]))
        )
        assert destination_path.is_relative_to(
            reconstruction.roots.attempt_root
        )
        assert not destination_path.is_relative_to(
            Path(str(source_inventory["attempt_root"]))
        )
        assert _file_digest(source_path) == byte_copy["sha256"]
        assert _file_digest(destination_path) == byte_copy["sha256"]
    assert (
        independently_verify_aox_closure_stage_reconstruction(
            reconstruction.receipt,
            plan=plan,
            source_manifest=manifest,
        )
        == reconstruction.receipt
    )
    baseline = _runtime_projection(
        SQLiteRepositoryProvider(str(reconstruction.roots.sqlite_path)),
        session_id=str(dict(plan["slot"])["session_id"]),
        attempt_id=reconstruction.scientific_attempt_id,
    )
    assert baseline["counts"]["controlled_operation"] == 6
    assert baseline["counts"]["pending_signal"] == 1
    assert baseline["counts"]["active_writer"] == 0
    with SQLiteRepositoryProvider(
        str(reconstruction.roots.sqlite_path)
    ).read() as scope:
        tasks = {
            task.task_id: task
            for task in scope.repositories.tasks.list_by_session(
                str(dict(plan["slot"])["session_id"])
            )
        }
        assert tasks[reconstruction.research_task_id].status.value == "completed"
        assert (
            tasks[str(dict(plan["slot"])["task_id"])].status.value
            == "in_progress"
        )
        assert tasks[reconstruction.report_task_id].status.value == "todo"
        artifacts = scope.repositories.artifacts.list_by_session(
            str(dict(plan["slot"])["session_id"])
        )
        assert artifacts
        assert all(
            isinstance(
                dict(artifact.metadata or {}).get(
                    "diagnostic_source_copy"
                ),
                dict,
            )
            for artifact in artifacts
        )
        assert all(
            dict(artifact.metadata or {})[
                "diagnostic_source_copy"
            ]["formal_adoption_eligible"]
            is False
            for artifact in artifacts
        )
        assert (
            scope.repositories.reports.list_by_session(
                str(dict(plan["slot"])["session_id"])
            )
            == []
        )
        assert (
            scope.repositories.report_drafts.list_by_session(
                str(dict(plan["slot"])["session_id"])
            )
            == []
        )
        assert (
            len(
                [
                    item
                    for item in scope.repositories.runtime_signals.list_by_session(
                        str(dict(plan["slot"])["session_id"])
                    )
                    if item.status.value == "pending"
                ]
            )
            == 1
        )
        finishes = [
            document
            for document in scope.repositories.engine_documents.list_by_session(
                str(dict(plan["slot"])["session_id"])
            )
            if document.document_kind == "task_finish"
        ]
        assert len(finishes) == 1
        assert finishes[0].payload["task_id"] == reconstruction.research_task_id
        delegations = [
            document
            for document in scope.repositories.engine_documents.list_by_session(
                str(dict(plan["slot"])["session_id"])
            )
            if document.document_kind == "delegation_request"
        ]
        executor_delegation = next(
            document
            for document in delegations
            if document.payload.get("role") == "executor"
        )
        assert executor_delegation.payload["workflow_refs"] == [
            _CURRENT_WORKFLOW_REF
        ]
        assert executor_delegation.payload["workflow_manifests"][0][
            "selection_ref"
        ] == _CURRENT_WORKFLOW_REF

    nested_extra = deepcopy(reconstruction.receipt)
    nested_extra["plan"]["unexpected_transform"] = "not-closed"
    nested_extra["plan"]["plan_digest"] = canonical_digest(
        {
            key: value
            for key, value in nested_extra["plan"].items()
            if key != "plan_digest"
        }
    )
    nested_extra["receipt_digest"] = canonical_digest(
        {
            key: value
            for key, value in nested_extra.items()
            if key != "receipt_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as extra:
        validate_aox_closure_stage_reconstruction_receipt(
            nested_extra,
            plan=plan,
            source_manifest=manifest,
        )
    assert extra.value.code == (
        "closure_stage_reconstruction_receipt_semantics_invalid"
    )

    omitted_row = deepcopy(reconstruction.receipt)
    row_receipt = next(
        item
        for item in omitted_row["table_imports"]
        if item["source_count"] > 1
    )
    row_receipt["keys"] = row_receipt["keys"][:-1]
    row_receipt["source_count"] -= 1
    row_receipt["target_count"] -= 1
    omitted_row["receipt_digest"] = canonical_digest(
        {
            key: value
            for key, value in omitted_row.items()
            if key != "receipt_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as missing_row:
        independently_verify_aox_closure_stage_reconstruction(
            omitted_row,
            plan=plan,
            source_manifest=manifest,
            requalify_source=False,
        )
    assert missing_row.value.code == (
        "closure_stage_reconstruction_row_plan_mismatch"
    )

    omitted_byte = deepcopy(reconstruction.receipt)
    assert omitted_byte["byte_copies"]
    omitted_byte["byte_copies"] = omitted_byte["byte_copies"][:-1]
    omitted_byte["receipt_digest"] = canonical_digest(
        {
            key: value
            for key, value in omitted_byte.items()
            if key != "receipt_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as missing_byte:
        independently_verify_aox_closure_stage_reconstruction(
            omitted_byte,
            plan=plan,
            source_manifest=manifest,
            requalify_source=False,
        )
    assert missing_byte.value.code == (
        "closure_stage_reconstruction_byte_plan_mismatch"
    )

    provider = SQLiteRepositoryProvider(
        str(reconstruction.roots.sqlite_path)
    )
    with provider.connection_scope() as scope:
        with MutationScopeService(scope.repositories).writer_turn(
            session_id=str(dict(plan["slot"])["session_id"]),
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref="test:post-reconstruction-runtime",
        ) as writer:
            assert writer is not None
            TaskBoardService(scope.repositories).finish_task(
                str(dict(plan["slot"])["task_id"]),
                TaskFinishCommand(
                    status=TaskStatus.COMPLETED,
                    finished_by=reconstruction.executor_agent_id,
                    summary="Simulated normal post-reconstruction task evolution.",
                    evidence_refs=(
                        "artifact:"
                        + str(
                            reconstruction.receipt[
                                "retained_identities"
                            ]["artifact_ids"][0]
                        ),
                    ),
                    next_owner="master",
                    correlation_id="test:post-reconstruction-runtime",
                ),
            )
    with pytest.raises(CutoverEvidenceError) as evolved_pristine:
        independently_verify_aox_closure_stage_reconstruction(
            reconstruction.receipt,
            plan=plan,
            source_manifest=manifest,
            requalify_source=False,
        )
    assert evolved_pristine.value.code == (
        "closure_stage_reconstruction_state_drift"
    )
    assert (
        independently_verify_aox_closure_stage_reconstruction(
            reconstruction.receipt,
            plan=plan,
            source_manifest=manifest,
            requalify_source=False,
            require_pristine_target=False,
        )
        == reconstruction.receipt
    )
