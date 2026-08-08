from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_core import ScientificWorkflowContract
from openzyme_core import ScientificWorkflowContractError
from openzyme_host_api import aox_architecture_qualification as qualification
from openzyme_host_api import aox_cutover_cli as cli
from openzyme_host_api.aox_architecture_qualification import (
    ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID,
)
from openzyme_host_api.aox_architecture_qualification import (
    ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V1,
)
from openzyme_host_api.aox_architecture_qualification import (
    ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V2,
)
from openzyme_host_api.aox_architecture_qualification import (
    AoxArchitectureQualificationError,
)
from openzyme_host_api.aox_architecture_qualification import (
    build_architecture_qualification_receipt,
)
from openzyme_host_api.aox_architecture_qualification import (
    normalize_architecture_qualification_receipt,
)
from openzyme_host_api.aox_architecture_qualification import (
    require_matching_architecture_qualification_receipt,
)
from openzyme_host_api.aox_attempt_authority import (
    AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID,
)
from openzyme_host_api.aox_attempt_authority import (
    AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
)
from openzyme_host_api.aox_attempt_preflight import ATTEMPT_PREFLIGHT_SCHEMA_ID
from openzyme_host_api.aox_cutover_launch import (
    AOX_SANDBOX_SCIENTIFIC_BACKEND_PROBE_SCHEMA_ID,
)
from openzyme_host_api.aox_cutover_runtime_config import (
    AOX_BLANK_WORLD_RUNTIME_CONFIG_LEGACY_SCHEMA_ID,
)
from openzyme_host_api.aox_cutover_runtime_config import (
    AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID,
)
from openzyme_host_api.aox_cutover_runtime_config import (
    AOX_BLANK_WORLD_RUNTIME_CONFIG_V2_SCHEMA_ID,
)
from openzyme_host_api.aox_cutover_runtime_config import (
    AOX_BLANK_WORLD_RUNTIME_CONFIG_V3_SCHEMA_ID,
)
from openzyme_host_api.aox_cutover_runtime_config import (
    AOX_BLANK_WORLD_RUNTIME_CONFIG_V4_SCHEMA_ID,
)
from openzyme_host_api.aox_launch_profile import (
    AOX_CUTOVER_LAUNCH_PROFILE_SCHEMA_ID,
)
from openzyme_host_api.aox_formal_slot_failure import (
    FORMAL_SLOT_FAILURE_SCHEMA_ID,
)
from openzyme_host_api.aox_formal_slot_failure import (
    LEGACY_FORMAL_SLOT_FAILURE_SCHEMA_ID,
)
from openzyme_host_api.aox_host_supervision import (
    HOST_PRE_READY_FAILURE_SCHEMA_ID,
)
from openzyme_host_api.aox_preflight_failure import (
    FORMAL_PREFLIGHT_FAILURE_DECISION_SCHEMA_ID,
)
from openzyme_host_api.aox_preflight_failure import (
    FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_ID,
)
from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_api.architecture_qualification import QUALIFICATION_REPORT_SCHEMA_ID
from openzyme_host_api.architecture_qualification import (
    QUALIFICATION_REPORT_SCHEMA_ID_V1,
)
from openzyme_host_api.architecture_qualification import (
    QUALIFICATION_REPORT_SCHEMA_ID_V2,
)

from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..external_ports import ExternalEffectLedger


_REPO_ROOT = Path(__file__).resolve().parents[5]
_ACTIVE_CUTOVER_SPEC = (
    _REPO_ROOT / "openspec/changes/aox-hmm-blank-world-cutover/specs/"
    "blank-world-live-cutover/spec.md"
)


def _digest(digit: str) -> str:
    return "sha256:" + digit * 64


def _requirement(document: str, title: str) -> str:
    header = f"### Requirement: {title}\n"
    if document.count(header) != 1:
        raise AssertionError(f"active contract must contain exactly one {header!r}")
    start = document.index(header)
    end = document.find("\n### Requirement:", start + len(header))
    return document[start:] if end < 0 else document[start:end]


def _replace_once(document: str, old: str, new: str) -> str:
    if document.count(old) != 1:
        raise AssertionError(f"contract mutation target is not unique: {old!r}")
    return document.replace(old, new, 1)


def _assert_current_schema_contract(document: str) -> dict[str, str]:
    launch = _requirement(document, "Canonical launch and prerequisite identity")
    if f"`{AOX_SANDBOX_SCIENTIFIC_BACKEND_PROBE_SCHEMA_ID}`" not in launch:
        raise AssertionError("active launch contract omits the current sandbox probe")
    if "`aox_exact_calculation_manifest@1`" not in launch:
        raise AssertionError("active launch contract omits exact calculation identity")
    current_config = f"`{AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID}` preimage"
    if current_config not in launch:
        raise AssertionError(
            "active launch contract does not bind current runtime config"
        )
    if "MUST NOT contain a `conductor` or `driver` policy object" not in launch:
        raise AssertionError("active launch contract permits conductor shadow truth")
    if "Its closed `conductor` object MUST bind" in launch:
        raise AssertionError("active launch contract restored the historical conductor")
    historical_configs = (
        AOX_BLANK_WORLD_RUNTIME_CONFIG_LEGACY_SCHEMA_ID,
        AOX_BLANK_WORLD_RUNTIME_CONFIG_V2_SCHEMA_ID,
        AOX_BLANK_WORLD_RUNTIME_CONFIG_V3_SCHEMA_ID,
        AOX_BLANK_WORLD_RUNTIME_CONFIG_V4_SCHEMA_ID,
    )
    for schema_id in historical_configs:
        if f"`{schema_id}`" not in launch:
            raise AssertionError(
                f"historical runtime config is not explicit: {schema_id}"
            )
        if f"`{schema_id}` preimage" in launch:
            raise AssertionError(f"historical runtime config was promoted: {schema_id}")
    if "MAY remain readable only for historical offline verification" not in launch:
        raise AssertionError("historical runtime configs lost their read-only boundary")
    for schema_id in (
        AOX_CUTOVER_LAUNCH_PROFILE_SCHEMA_ID,
        AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
        AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID,
        ATTEMPT_PREFLIGHT_SCHEMA_ID,
        FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID,
        FORMAL_PREFLIGHT_FAILURE_DECISION_SCHEMA_ID,
    ):
        if f"`{schema_id}`" not in launch:
            raise AssertionError(f"active launch contract omits {schema_id}")
    if "Ambient state MAY supply only credentials" not in launch:
        raise AssertionError("active launch contract permits ambient profile fallback")
    if "MUST NOT be retroactively backfilled" not in launch:
        raise AssertionError("active launch contract permits historical backfill")

    launch_failure = _requirement(
        document,
        "可验证且脱敏的启动配置与失败因果",
    )
    if "sandbox runtime branch MUST 使用 exact `kind=sandbox_runtime`" not in launch_failure:
        raise AssertionError("active launch failure omits the sandbox runtime branch")
    for failure_code in (
        "pipeline_sdk_source_unavailable",
        "podman_binary_unavailable",
        "podman_rootless_preflight_failed",
        "sandbox_image_identity_invalid",
        "sandbox_image_unavailable",
        "sandbox_runtime_identity_drift",
    ):
        if f"`{failure_code}`" not in launch_failure:
            raise AssertionError(
                f"sandbox runtime failure allowlist omits {failure_code}"
            )

    conductor = _requirement(
        document,
        "Authority-bound public conductor production reachability",
    )
    for schema_id in (
        FORMAL_SLOT_FAILURE_SCHEMA_ID,
        HOST_PRE_READY_FAILURE_SCHEMA_ID,
    ):
        if f"`{schema_id}`" not in conductor:
            raise AssertionError(f"active conductor contract omits {schema_id}")
    if "immediately before slot claim" not in conductor:
        raise AssertionError("preflight does not require the actual pre-claim guard")
    if "closure_mode=pre_child_ready" not in conductor:
        raise AssertionError("pre-ready failure mode is not explicit")
    if (
        f"Historical `{LEGACY_FORMAL_SLOT_FAILURE_SCHEMA_ID}`"
        not in conductor
    ):
        raise AssertionError("legacy formal slot failure lost read-only status")

    admission = _requirement(
        document,
        "AOX current admission consumes current source-causal qualification only",
    )
    current_pair = (
        f"verified `{QUALIFICATION_REPORT_SCHEMA_ID}` and matching "
        f"`{ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID}`"
    )
    if current_pair not in admission:
        raise AssertionError("active admission contract does not bind current schemas")
    for field in (
        "owner_constraint_registry_digest",
        "transformation_results_digest",
    ):
        if f"`{field}`" not in admission:
            raise AssertionError(f"current qualification receipt omits {field}")
    historical_qualification = (
        QUALIFICATION_REPORT_SCHEMA_ID_V1,
        QUALIFICATION_REPORT_SCHEMA_ID_V2,
        ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V1,
        ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V2,
    )
    for schema_id in historical_qualification:
        if f"`{schema_id}`" not in admission:
            raise AssertionError(
                f"historical qualification is not explicit: {schema_id}"
            )
    if "MAY remain readable only for frozen bundle compatibility" not in admission:
        raise AssertionError("historical qualification lost its read-only boundary")
    return {
        "qualification_receipt_schema_id": (
            ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID
        ),
        "qualification_report_schema_id": QUALIFICATION_REPORT_SCHEMA_ID,
        "runtime_config_schema_id": AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID,
        "launch_profile_schema_id": AOX_CUTOVER_LAUNCH_PROFILE_SCHEMA_ID,
        "authority_plan_schema_id": AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
        "authority_consumption_schema_id": (
            AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID
        ),
        "preflight_schema_id": ATTEMPT_PREFLIGHT_SCHEMA_ID,
        "preflight_failure_schema_id": FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID,
        "preflight_failure_decision_schema_id": (
            FORMAL_PREFLIGHT_FAILURE_DECISION_SCHEMA_ID
        ),
        "formal_slot_failure_schema_id": FORMAL_SLOT_FAILURE_SCHEMA_ID,
        "host_pre_ready_failure_schema_id": HOST_PRE_READY_FAILURE_SCHEMA_ID,
        "sandbox_probe_schema_id": (
            AOX_SANDBOX_SCIENTIFIC_BACKEND_PROBE_SCHEMA_ID
        ),
    }


@pytest.mark.architecture_qualification_scenario(
    scenario_id="evidence-projection.aox-admission-receipt-closure",
    family="evidence-projection",
    selections=("full", "premerge_subset"),
)
def test_aox_admission_precedes_roots_and_receipt_closes_exact_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_bytes = _ACTIVE_CUTOVER_SPEC.read_bytes()
    spec_document = spec_bytes.decode("utf-8")
    schema_contract = _assert_current_schema_contract(spec_document)
    contract_drift_mutations = {
        "conductor_shadow_truth": _replace_once(
            spec_document,
            "MUST NOT contain a `conductor` or `driver` policy object",
            "MUST contain a `conductor` policy object",
        ),
        "historical_qualification_promoted": _replace_once(
            spec_document,
            (
                f"verified `{QUALIFICATION_REPORT_SCHEMA_ID}` and matching "
                f"`{ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID}`"
            ),
            (
                f"verified `{QUALIFICATION_REPORT_SCHEMA_ID_V2}` and matching "
                f"`{ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID_V2}`"
            ),
        ),
        "historical_runtime_config_promoted": _replace_once(
            spec_document,
            f"`{AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID}` preimage",
            f"`{AOX_BLANK_WORLD_RUNTIME_CONFIG_V4_SCHEMA_ID}` preimage",
        ),
        "owner_constraint_binding_removed": _replace_once(
            spec_document,
            "`owner_constraint_registry_digest`",
            "`legacy_registry_digest`",
        ),
        "transformation_binding_removed": _replace_once(
            spec_document,
            "`transformation_results_digest`",
            "`legacy_transformation_digest`",
        ),
        "launch_profile_binding_removed": _replace_once(
            spec_document,
            (
                "one closed credential-free "
                f"`{AOX_CUTOVER_LAUNCH_PROFILE_SCHEMA_ID}`"
            ),
            "one unbound ambient launch profile",
        ),
        "preflight_failure_closure_removed": _replace_once(
            spec_document,
            f"one source-bound `{FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID}` sibling",
            "one unbound preflight failure note",
        ),
    }
    rejected_contract_drifts: list[str] = []
    for mutation, drifted_document in sorted(contract_drift_mutations.items()):
        with pytest.raises(AssertionError):
            _assert_current_schema_contract(drifted_document)
        rejected_contract_drifts.append(mutation)

    loaded = SimpleNamespace(
        envelope={"schema_id": QUALIFICATION_REPORT_SCHEMA_ID},
        payload={},
    )
    monkeypatch.setattr(qualification, "load_report", lambda path: loaded)
    monkeypatch.setattr(
        qualification,
        "verify_report",
        lambda report, *, repo_root, runner_path: SimpleNamespace(
            admission_eligible=False,
            payload_digest=_digest("1"),
            rejection_reasons=("mode_not_admission",),
            source_commit="a" * 40,
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_aox_architecture_qualification_report",
        qualification.verify_aox_architecture_qualification_report,
    )
    root_calls: list[object] = []

    def reject_root_creation(*args: object, **kwargs: object) -> None:
        root_calls.append((args, kwargs))
        raise AssertionError("AOX root creation crossed a rejected admission gate")

    monkeypatch.setattr(cli, "create_blank_world_roots", reject_root_creation)
    campaign_root = tmp_path / "campaign"
    args = cli.build_parser().parse_args(
        [
            "preflight",
            "--campaign-root",
            str(campaign_root),
            "--identity",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites",
            str(tmp_path / "allowed-prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "qualification-report.json"),
            "--attempt-authority-plan",
            str(tmp_path / "attempt-authority.json"),
            "--attempt-authority-consumption",
            str(tmp_path / "attempt-authority-consumption.json"),
            "--slot-ordinal",
            "1",
        ]
    )

    with pytest.raises(AoxArchitectureQualificationError) as gate_error:
        cli._preflight(args)

    assert gate_error.value.code == "aox_architecture_qualification_not_admissible"
    assert root_calls == []
    assert not campaign_root.exists()

    receipt = build_architecture_qualification_receipt(
        report_payload_digest=_digest("1"),
        registry_digest=_digest("2"),
        test_manifest_digest=_digest("3"),
        profile_id="local_single_process_file_sqlite@1",
        source_commit="a" * 40,
        report_schema_id=QUALIFICATION_REPORT_SCHEMA_ID,
        run_evidence_digest=_digest("5"),
        source_identity_digest=_digest("6"),
        owner_constraint_registry_digest=_digest("7"),
        transformation_results_digest=_digest("8"),
    )
    assert (
        normalize_architecture_qualification_receipt(
            receipt,
            expected_source_commit="a" * 40,
        )
        == receipt
    )

    tampered = deepcopy(receipt)
    tampered["report_payload_digest"] = _digest("4")
    with pytest.raises(AoxArchitectureQualificationError) as digest_error:
        normalize_architecture_qualification_receipt(tampered)
    assert digest_error.value.code == "aox_architecture_qualification_receipt_invalid"

    different_report = build_architecture_qualification_receipt(
        report_payload_digest=_digest("4"),
        registry_digest=_digest("2"),
        test_manifest_digest=_digest("3"),
        profile_id="local_single_process_file_sqlite@1",
        source_commit="a" * 40,
        report_schema_id=QUALIFICATION_REPORT_SCHEMA_ID,
        run_evidence_digest=_digest("5"),
        source_identity_digest=_digest("6"),
        owner_constraint_registry_digest=_digest("7"),
        transformation_results_digest=_digest("8"),
    )
    with pytest.raises(AoxArchitectureQualificationError) as mismatch_error:
        require_matching_architecture_qualification_receipt(receipt, different_report)
    assert mismatch_error.value.code == (
        "aox_architecture_qualification_receipt_mismatch"
    )

    active_contract = AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY.resolve(
        workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
        workflow_contract_digest=(AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST),
        for_new_attempt=True,
    )
    assert isinstance(active_contract, ScientificWorkflowContract)
    assert active_contract.digest == (
        "sha256:ab9898f52fc9fd1f1dc8b6498d368ba68d2e658c1ebc819cb76f73b7737de922"
    )
    assert AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID == (
        "aox_blank_world_runtime_config@5"
    )
    assert QUALIFICATION_REPORT_SCHEMA_ID == (
        "openzyme_v3_architecture_qualification_report@3"
    )
    assert ARCHITECTURE_QUALIFICATION_RECEIPT_SCHEMA_ID == (
        "aox_architecture_qualification_receipt@3"
    )
    assert AOX_CUTOVER_LAUNCH_PROFILE_SCHEMA_ID == "aox_cutover_launch_profile@1"
    assert AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID == (
        "aox_live_attempt_authority_plan@4"
    )
    assert AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID == (
        "aox_live_attempt_authority_consumption@5"
    )
    assert ATTEMPT_PREFLIGHT_SCHEMA_ID == "aox_attempt_preflight@5"
    assert FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID == "aox_formal_preflight_failure@1"
    assert FORMAL_PREFLIGHT_FAILURE_DECISION_SCHEMA_ID == (
        "aox_blank_world_campaign_preflight_failure_decision@1"
    )
    host_supervision_source = (
        _REPO_ROOT
        / "apps/openzyme-host-api/src/openzyme_host_api/aox_host_supervision.py"
    ).read_text(encoding="utf-8")
    assert "resolve_aox_cutover_launch_profile" in host_supervision_source
    assert "OpenZymeSettings.from_env()" not in host_supervision_source
    preflight_source = inspect.getsource(cli._preflight)
    prepare_position = preflight_source.index("prepare_aox_cutover_launch(")
    guard_position = preflight_source.index("launch.assert_unchanged()")
    claim_position = preflight_source.index("claim_aox_attempt_authority_slot(")
    root_position = preflight_source.index("create_blank_world_roots(")
    assert prepare_position < guard_position < claim_position < root_position
    assert "build_aox_cutover_effective_config(" not in preflight_source
    with pytest.raises(ScientificWorkflowContractError) as historical_error:
        AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY.resolve(
            workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
            workflow_contract_digest=(AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_V1_DIGEST),
            for_new_attempt=True,
        )
    assert historical_error.value.error_code == (
        "workflow_contract_historical_read_only"
    )

    observation = {
        "active_cutover_spec_digest": (
            "sha256:" + hashlib.sha256(spec_bytes).hexdigest()
        ),
        "admission_error_code": gate_error.value.code,
        "campaign_root_created": campaign_root.exists(),
        "contract_drift_rejections": rejected_contract_drifts,
        "digest_tamper_error_code": digest_error.value.code,
        "receipt": receipt,
        "receipt_mismatch_error_code": mismatch_error.value.code,
        "root_call_count": len(root_calls),
        "runtime_config_schema_id": (AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID),
        "schema_contract": schema_contract,
        "schema_id": "aox_architecture_qualification_observation@1",
        "selected_chain_contract_digest": active_contract.digest,
        "selected_chain_historical_rejection": (historical_error.value.error_code),
    }
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    )
    record_effect_ledger_snapshot(ExternalEffectLedger().snapshot())
