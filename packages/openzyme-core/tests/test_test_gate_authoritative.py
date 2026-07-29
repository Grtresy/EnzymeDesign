from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.authoritative import (  # noqa: E402
    AuthoritativePlanError,
    MAINLINE_AUTHORITATIVE_PLAN_FILENAME,
    NODE_MANIFEST_FILENAME,
    PLAN_FILENAME,
    build_authoritative_mainline_plan,
    build_authoritative_shadow_plan,
    build_node_manifest,
    stage_environments,
    verify_authoritative_plan,
    verify_node_manifest,
)
from scripts.test_gate.authoritative_runner import (  # noqa: E402
    AuthoritativeRunnerError,
    MAINLINE_AUTHORITATIVE_RECEIPT_FILENAME,
    MAINLINE_CANDIDATE_RECEIPT_FILENAME,
    build_authoritative_receipt,
    load_and_verify_qualification_sidecar,
    run_fail_fast_stage_sequence,
    verify_authoritative_candidate_output,
    verify_authoritative_mainline_output,
    verify_authoritative_receipt_documents,
)
from scripts.test_gate import authoritative_runner  # noqa: E402
from scripts.test_gate.config import load_config  # noqa: E402
from scripts.test_gate.model import (  # noqa: E402
    EXECUTION_PLAN_SCHEMA_ID,
    NODE_MANIFEST_SCHEMA_ID,
    canonical_json_bytes,
    canonical_document_bytes,
    load_canonical_document_bytes,
    seal_document,
    sha256_digest,
)
from scripts.test_gate.shadow import (  # noqa: E402
    CollectionSnapshot,
    ShadowCollectionResult,
    close_shadow_coverage,
)
from scripts.test_gate.source import SourceIdentity  # noqa: E402
from scripts.test_gate.runner import ProcessResult, StreamCapture  # noqa: E402

CONFIG_PATH = REPOSITORY_ROOT / "scripts/test-gate.toml"


def _snapshot(
    role: str,
    nodes: tuple[str, ...],
    *,
    deselected: tuple[tuple[str, tuple[str, ...]], ...] = (),
    marker_overrides: dict[str, tuple[str, ...]] | None = None,
) -> CollectionSnapshot:
    marker_overrides = marker_overrides or {}
    markers = tuple(
        (node_id, marker_overrides.get(node_id, ())) for node_id in nodes
    )
    canonical = [
        {"node_id": node_id, "markers": list(marker_names)}
        for node_id, marker_names in markers
    ]
    return CollectionSnapshot(
        invocation_id="invocation-1",
        role=role,
        nodes=nodes,
        markers=markers,
        digest=sha256_digest(canonical_json_bytes(canonical)),
        deselected_markers=deselected,
    )


def _source() -> SourceIdentity:
    return SourceIdentity(
        commit="a" * 40,
        tracked_diff_digest="sha256:" + "1" * 64,
        tracked_dirty_paths=("scripts/test_gate/authoritative.py",),
        relevant_untracked_sources=(),
        configurations=(),
        locks=(),
        toolchains=(),
    )


def _shadow(
    output_root: Path,
    *,
    general: CollectionSnapshot | None = None,
    harness: CollectionSnapshot | None = None,
    scenarios: CollectionSnapshot | None = None,
) -> ShadowCollectionResult:
    source = _source()
    general = general or _snapshot(
        "legacy_general",
        ("test_a.py::test_a", "test_b.py::test_b", "test_c.py::test_c"),
        deselected=(
            ("test_live.py::test_live", ("integration", "live_hpc")),
        ),
    )
    harness = harness or _snapshot(
        "qualification_harness",
        ("test_b.py::test_b",),
    )
    scenarios = scenarios or _snapshot(
        "qualification_scenario",
        ("test_c.py::test_c",),
        marker_overrides={
            "test_c.py::test_c": ("architecture_qualification_scenario",)
        },
    )
    coverage = close_shadow_coverage(
        invocation_id="invocation-1",
        source_identity_digest=source.digest,
        general=general,
        qualification_harness=harness,
        qualification_scenarios=scenarios,
    )
    return ShadowCollectionResult(
        output_root=output_root,
        source_identity=source,
        general=general,
        qualification_harness=harness,
        qualification_scenarios=scenarios,
        coverage_document=coverage,
    )


def _plan_fixture(
    tmp_path: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, dict[str, str]],
]:
    output_root = tmp_path / "evidence"
    output_root.mkdir()
    config = load_config(CONFIG_PATH)
    environments = stage_environments(
        config=config,
        repo_root=REPOSITORY_ROOT,
        source={"PATH": "/usr/bin", "LANG": "C"},
    )
    plan = build_authoritative_shadow_plan(
        repo_root=REPOSITORY_ROOT,
        output_root=output_root,
        config=config,
        invocation_id="invocation-1",
        shadow=_shadow(output_root),
        environments=environments,
    )
    manifest = build_node_manifest(plan)
    return plan, manifest, environments


def _mainline_plan_fixture(
    tmp_path: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, dict[str, str]],
]:
    output_root = tmp_path / "authoritative-evidence"
    output_root.mkdir()
    config = load_config(CONFIG_PATH)
    environments = stage_environments(
        config=config,
        repo_root=REPOSITORY_ROOT,
        source={"PATH": "/usr/bin", "LANG": "C"},
    )
    plan = build_authoritative_mainline_plan(
        repo_root=REPOSITORY_ROOT,
        output_root=output_root,
        config=config,
        invocation_id="authoritative-invocation-1",
        shadow=_shadow(output_root),
        environments=environments,
    )
    manifest = build_node_manifest(plan)
    return plan, manifest, environments


def _reseal(document: dict[str, object]) -> dict[str, object]:
    fields = dict(document)
    schema_id = str(fields.pop("schema_id"))
    fields.pop("self_digest")
    return seal_document(schema_id, fields)


def test_shadow_plan_closes_obligations_owners_and_exact_manifest(
    tmp_path: Path,
) -> None:
    plan, manifest, environments = _plan_fixture(tmp_path)
    config = load_config(CONFIG_PATH)

    verify_authoritative_plan(
        plan,
        repo_root=REPOSITORY_ROOT,
        config=config,
        current_source_identity_digest=_source().digest,
        current_environments=environments,
    )
    verify_node_manifest(manifest, plan=plan)

    assert plan["schema_id"] == EXECUTION_PLAN_SCHEMA_ID
    assert plan["authority"]["authoritative"] is False
    assert [stage["stage_id"] for stage in plan["stages"]] == [
        "ruff_source",
        "ruff_compatibility_audit",
        "compatibility_audit",
        "architecture_qualification_premerge",
        "general_non_live_pytest",
        "web_ui_test",
        "web_ui_build",
    ]
    general_stage = next(
        stage
        for stage in plan["stages"]
        if stage["stage_id"] == "general_non_live_pytest"
    )
    assert general_stage["argv"][:3] == [
        sys.executable,
        "scripts/run-test-gate.py",
        "execute-general-plan",
    ]
    assert general_stage["configured_argv"][:3] == ["uv", "run", "pytest"]
    assert manifest["schema_id"] == NODE_MANIFEST_SCHEMA_ID
    assert manifest["selected_nodes"] == ["test_a.py::test_a"]
    assert manifest["planned_deselected_nodes"] == [
        "test_b.py::test_b",
        "test_c.py::test_c",
    ]
    assert manifest["expected_policy_deselected_nodes"] == [
        "test_live.py::test_live"
    ]


def test_authority_modes_have_distinct_files_commands_and_verifier_domains(
    tmp_path: Path,
) -> None:
    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir()
    shadow_plan, _, shadow_environments = _plan_fixture(shadow_root)
    plan, manifest, environments = _mainline_plan_fixture(tmp_path)
    config = load_config(CONFIG_PATH)

    verify_authoritative_plan(
        plan,
        repo_root=REPOSITORY_ROOT,
        config=config,
        current_source_identity_digest=_source().digest,
        current_environments=environments,
        expected_authoritative=True,
    )
    verify_node_manifest(manifest, plan=plan)

    assert plan["authority"] == {
        "authoritative": True,
        "profile_contract_authoritative": True,
        "admission_eligible": False,
        "live_eligible": False,
        "authority_domain": "authoritative_non_live_mainline",
        "current_authoritative_entry": "scripts/check-mainline.sh",
    }
    general_stage = next(
        stage
        for stage in plan["stages"]
        if stage["stage_id"] == "general_non_live_pytest"
    )
    assert str(
        Path(plan["output_root"]) / MAINLINE_AUTHORITATIVE_PLAN_FILENAME
    ) in general_stage["argv"]
    assert general_stage["argv"][-1] == "--authoritative-mainline"
    assert MAINLINE_AUTHORITATIVE_PLAN_FILENAME != PLAN_FILENAME
    assert (
        MAINLINE_AUTHORITATIVE_RECEIPT_FILENAME
        != MAINLINE_CANDIDATE_RECEIPT_FILENAME
    )

    with pytest.raises(
        AuthoritativePlanError,
        match="crossed verifier domains",
    ):
        verify_authoritative_plan(
            plan,
            repo_root=REPOSITORY_ROOT,
            config=config,
            current_source_identity_digest=_source().digest,
            current_environments=environments,
        )
    with pytest.raises(
        AuthoritativePlanError,
        match="crossed verifier domains",
    ):
        verify_authoritative_plan(
            shadow_plan,
            repo_root=REPOSITORY_ROOT,
            config=config,
            current_source_identity_digest=_source().digest,
            current_environments=shadow_environments,
            expected_authoritative=True,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda plan: plan["node_ownership"].pop(),
            "exactly one expected owner",
        ),
        (
            lambda plan: plan["stages"][4]["argv"].append("-k"),
            "stage order, command, dependency, or policy drifted",
        ),
        (
            lambda plan: plan["stages"][4].update(
                {"argv": list(plan["stages"][4]["configured_argv"])}
            ),
            "stage order, command, dependency, or policy drifted",
        ),
        (
            lambda plan: plan["worker_policy"].update({"workers": 2}),
            "worker policy drifted",
        ),
    ),
)
def test_plan_verifier_rejects_owner_command_and_worker_drift(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    plan, _, environments = _plan_fixture(tmp_path)
    mutable = dict(plan)
    mutable["stages"] = [dict(item) for item in plan["stages"]]
    mutable["node_ownership"] = [
        dict(item) for item in plan["node_ownership"]
    ]
    mutable["worker_policy"] = dict(plan["worker_policy"])
    mutation(mutable)
    tampered = _reseal(mutable)

    with pytest.raises(AuthoritativePlanError, match=message):
        verify_authoritative_plan(
            tampered,
            repo_root=REPOSITORY_ROOT,
            config=load_config(CONFIG_PATH),
            current_environments=environments,
        )


def test_plan_rejects_marker_source_config_and_environment_drift(
    tmp_path: Path,
) -> None:
    plan, _, environments = _plan_fixture(tmp_path)
    marker_drift = dict(plan)
    marker_drift["collections"] = dict(plan["collections"])
    marker_drift["collections"]["general"] = dict(
        plan["collections"]["general"]
    )
    marker_drift["collections"]["general"]["markers"] = [
        dict(item) for item in plan["collections"]["general"]["markers"]
    ]
    marker_drift["collections"]["general"]["markers"][0] = {
        "node_id": "test_a.py::test_a",
        "markers": ["unregistered_marker"],
    }
    marker_drift = _reseal(marker_drift)
    with pytest.raises(AuthoritativePlanError, match="unknown or forbidden"):
        verify_authoritative_plan(
            marker_drift,
            repo_root=REPOSITORY_ROOT,
            config=load_config(CONFIG_PATH),
        )

    with pytest.raises(AuthoritativePlanError, match="source identity is stale"):
        verify_authoritative_plan(
            plan,
            repo_root=REPOSITORY_ROOT,
            config=load_config(CONFIG_PATH),
            current_source_identity_digest="sha256:" + "f" * 64,
        )

    drifted_environments = {
        stage_id: dict(environment)
        for stage_id, environment in environments.items()
    }
    drifted_environments["general_non_live_pytest"]["DRIFT"] = "1"
    with pytest.raises(AuthoritativePlanError, match="environment"):
        verify_authoritative_plan(
            plan,
            repo_root=REPOSITORY_ROOT,
            config=load_config(CONFIG_PATH),
            current_environments=drifted_environments,
        )


def test_plan_fails_before_execution_when_qualification_is_not_in_g(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "evidence"
    output_root.mkdir()
    config = load_config(CONFIG_PATH)
    source = _source()
    shadow = ShadowCollectionResult(
        output_root=output_root,
        source_identity=source,
        general=_snapshot("legacy_general", ("test_a.py::test_a",)),
        qualification_harness=_snapshot(
            "qualification_harness",
            ("test_missing.py::test_missing",),
        ),
        qualification_scenarios=_snapshot("qualification_scenario", ()),
        coverage_document={
            "terminal_status": "pass",
            "source_identity_digest": source.digest,
        },
    )
    with pytest.raises(
        AuthoritativePlanError,
        match="qualification-owned nodes are missing from G",
    ):
        build_authoritative_shadow_plan(
            repo_root=REPOSITORY_ROOT,
            output_root=output_root,
            config=config,
            invocation_id="invocation-1",
            shadow=shadow,
            environments=stage_environments(
                config=config,
                repo_root=REPOSITORY_ROOT,
                source={"PATH": "/usr/bin"},
            ),
        )


def test_manifest_verifier_rejects_prior_plan_and_partition_drift(
    tmp_path: Path,
) -> None:
    plan, manifest, _ = _plan_fixture(tmp_path)
    prior = dict(manifest)
    prior["plan_digest"] = "sha256:" + "0" * 64
    prior = _reseal(prior)
    with pytest.raises(AuthoritativePlanError, match="plan binding drifted"):
        verify_node_manifest(prior, plan=plan)

    partition = dict(manifest)
    partition["selected_nodes"] = []
    partition["selected_nodes_digest"] = sha256_digest(
        canonical_json_bytes([])
    )
    partition = _reseal(partition)
    with pytest.raises(AuthoritativePlanError, match="selected_nodes"):
        verify_node_manifest(partition, plan=plan)


def test_authoritative_environment_rejects_ambient_pytest_mutators() -> None:
    config = load_config(CONFIG_PATH)
    with pytest.raises(AuthoritativePlanError, match="PYTEST_ADDOPTS"):
        stage_environments(
            config=config,
            repo_root=REPOSITORY_ROOT,
            source={"PATH": "/usr/bin", "PYTEST_ADDOPTS": "-k hidden"},
        )


def _process_result(
    argv: tuple[str, ...],
    cwd: Path,
    *,
    outcome: str,
    timed_out: bool = False,
) -> ProcessResult:
    capture = StreamCapture(
        digest="sha256:" + "0" * 64,
        total_bytes=0,
        tail="",
    )
    return ProcessResult(
        argv=argv,
        cwd=str(cwd),
        outcome=outcome,
        exit_code=(None if timed_out else (0 if outcome == "pass" else 1)),
        started_monotonic_ns=100,
        duration_ns=10,
        stdout=capture,
        stderr=capture,
        timed_out=timed_out,
        term_sent=False,
        kill_sent=False,
        error=None,
    )


def _pass_stage_sequence(
    tmp_path: Path,
    *,
    authoritative: bool = False,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, dict[str, str]],
    object,
]:
    plan, manifest, environments = (
        _mainline_plan_fixture(tmp_path)
        if authoritative
        else _plan_fixture(tmp_path)
    )

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: float,
    ) -> ProcessResult:
        del environment, timeout_seconds
        return _process_result(argv, cwd, outcome="pass")

    sequence = run_fail_fast_stage_sequence(
        plan=plan,
        manifest=manifest,
        repo_root=REPOSITORY_ROOT,
        config=load_config(CONFIG_PATH),
        environments=environments,
        process_runner=runner,
        source_collector=lambda _: _source(),
        expected_authoritative=authoritative,
    )
    return plan, manifest, environments, sequence


def _green_node_results(plan: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "node_id": item["node_id"],
            "owner": item["owner"],
            "outcome": (
                "xfail"
                if item["owner"] == "general_non_live_pytest"
                else "pass"
            ),
            "duration_ns": 5,
        }
        for item in plan["node_ownership"]
    ]


def _qualification_receipt(
    plan: dict[str, object],
    node_results: list[dict[str, object]],
) -> dict[str, object]:
    qualification_results = [
        item
        for item in node_results
        if item["owner"] == "architecture_qualification_premerge"
    ]
    return {
        "status": "verified",
        "sidecar_path": "qualification-execution.json",
        "sidecar_digest": "sha256:" + "3" * 64,
        "report_digest": "sha256:" + "4" * 64,
        "harness_nodes": plan["collections"]["qualification_harness"][
            "nodes"
        ],
        "scenario_nodes": plan["collections"]["qualification_scenarios"][
            "nodes"
        ],
        "node_results_digest": sha256_digest(
            canonical_json_bytes(qualification_results)
        ),
    }


def _green_receipt_fixture(
    tmp_path: Path,
    *,
    authoritative: bool = False,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, dict[str, object]],
]:
    plan, manifest, _, sequence = _pass_stage_sequence(
        tmp_path,
        authoritative=authoritative,
    )
    node_results = _green_node_results(plan)
    receipt = build_authoritative_receipt(
        plan=plan,
        manifest=manifest,
        receipt_stages=sequence.receipt_stages,
        node_results=node_results,
        unexpected_deselected=(),
        frontend_outcomes={
            "web_ui_test": "pass",
            "web_ui_build": "pass",
        },
        qualification=_qualification_receipt(plan, node_results),
        total_duration_ns=1000,
        general_recheck_observation_digest="sha256:" + "5" * 64,
        general_execution_observation_digest="sha256:" + "6" * 64,
    )
    return plan, manifest, receipt, sequence.stage_documents


def test_fail_fast_runner_never_starts_dependent_stages(
    tmp_path: Path,
) -> None:
    plan, manifest, environments = _plan_fixture(tmp_path)
    calls: list[str] = []

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: float,
    ) -> ProcessResult:
        del environment, timeout_seconds
        stage_id = plan["stages"][len(calls)]["stage_id"]
        calls.append(stage_id)
        outcome = "fail" if stage_id == "compatibility_audit" else "pass"
        return _process_result(argv, cwd, outcome=outcome)

    sequence = run_fail_fast_stage_sequence(
        plan=plan,
        manifest=manifest,
        repo_root=REPOSITORY_ROOT,
        config=load_config(CONFIG_PATH),
        environments=environments,
        process_runner=runner,
        source_collector=lambda _: _source(),
    )

    assert calls == [
        "ruff_source",
        "ruff_compatibility_audit",
        "compatibility_audit",
    ]
    assert sequence.first_failing_stage == "compatibility_audit"
    assert [item["status"] for item in sequence.receipt_stages] == [
        "ran",
        "ran",
        "ran",
        "not_run",
        "not_run",
        "not_run",
        "not_run",
    ]


def test_timeout_is_terminal_evidence_and_blocks_every_dependent_stage(
    tmp_path: Path,
) -> None:
    plan, manifest, environments = _plan_fixture(tmp_path)

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: float,
    ) -> ProcessResult:
        del environment, timeout_seconds
        return _process_result(
            argv,
            cwd,
            outcome="timeout",
            timed_out=True,
        )

    sequence = run_fail_fast_stage_sequence(
        plan=plan,
        manifest=manifest,
        repo_root=REPOSITORY_ROOT,
        config=load_config(CONFIG_PATH),
        environments=environments,
        process_runner=runner,
        source_collector=lambda _: _source(),
    )
    receipt = build_authoritative_receipt(
        plan=plan,
        manifest=manifest,
        receipt_stages=sequence.receipt_stages,
        node_results=(),
        unexpected_deselected=(),
        frontend_outcomes={
            "web_ui_test": "not_run",
            "web_ui_build": "not_run",
        },
        qualification={
            "status": "not_run",
            "sidecar_path": None,
            "sidecar_digest": None,
            "report_digest": None,
            "harness_nodes": [],
            "scenario_nodes": [],
            "node_results_digest": sha256_digest(canonical_json_bytes([])),
        },
        total_duration_ns=10,
        general_recheck_observation_digest=None,
        general_execution_observation_digest=None,
    )

    verify_authoritative_receipt_documents(
        plan=plan,
        manifest=manifest,
        receipt=receipt,
        stage_documents=sequence.stage_documents,
        repo_root=REPOSITORY_ROOT,
        config=load_config(CONFIG_PATH),
        current_source_identity_digest=_source().digest,
    )
    assert sequence.first_failing_stage == "ruff_source"
    assert receipt["terminal_status"] == "fail"
    assert [item["status"] for item in sequence.receipt_stages] == [
        "ran",
        "not_run",
        "not_run",
        "not_run",
        "not_run",
        "not_run",
        "not_run",
    ]


@pytest.mark.parametrize("qualification_outcome", ("fail", "timeout"))
def test_qualification_failure_or_timeout_never_starts_general_fallback(
    tmp_path: Path,
    qualification_outcome: str,
) -> None:
    plan, manifest, environments = _plan_fixture(tmp_path)
    calls: list[str] = []

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: float,
    ) -> ProcessResult:
        del environment, timeout_seconds
        stage_id = plan["stages"][len(calls)]["stage_id"]
        calls.append(stage_id)
        if stage_id != "architecture_qualification_premerge":
            return _process_result(argv, cwd, outcome="pass")
        return _process_result(
            argv,
            cwd,
            outcome=qualification_outcome,
            timed_out=qualification_outcome == "timeout",
        )

    sequence = run_fail_fast_stage_sequence(
        plan=plan,
        manifest=manifest,
        repo_root=REPOSITORY_ROOT,
        config=load_config(CONFIG_PATH),
        environments=environments,
        process_runner=runner,
        source_collector=lambda _: _source(),
    )

    assert calls == [
        "ruff_source",
        "ruff_compatibility_audit",
        "compatibility_audit",
        "architecture_qualification_premerge",
    ]
    assert sequence.first_failing_stage == (
        "architecture_qualification_premerge"
    )
    assert [item["status"] for item in sequence.receipt_stages[4:]] == [
        "not_run",
        "not_run",
        "not_run",
    ]


def test_green_receipt_closes_stage_node_frontend_and_outcome_sets(
    tmp_path: Path,
) -> None:
    plan, manifest, receipt, stage_documents = _green_receipt_fixture(
        tmp_path
    )
    verify_authoritative_receipt_documents(
        plan=plan,
        manifest=manifest,
        receipt=receipt,
        stage_documents=stage_documents,
        repo_root=REPOSITORY_ROOT,
        config=load_config(CONFIG_PATH),
        current_source_identity_digest=_source().digest,
    )

    assert receipt["terminal_status"] == "pass"
    assert receipt["authoritative"] is False
    assert [
        item["outcome"] for item in receipt["coverage"]["node_results"]
    ] == ["xfail", "pass", "pass"]


def test_authoritative_receipt_requires_the_authoritative_verifier_domain(
    tmp_path: Path,
) -> None:
    plan, manifest, environments = _mainline_plan_fixture(tmp_path)

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: float,
    ) -> ProcessResult:
        del environment, timeout_seconds
        return _process_result(argv, cwd, outcome="pass")

    sequence = run_fail_fast_stage_sequence(
        plan=plan,
        manifest=manifest,
        repo_root=REPOSITORY_ROOT,
        config=load_config(CONFIG_PATH),
        environments=environments,
        process_runner=runner,
        source_collector=lambda _: _source(),
        expected_authoritative=True,
    )
    node_results = _green_node_results(plan)
    receipt = build_authoritative_receipt(
        plan=plan,
        manifest=manifest,
        receipt_stages=sequence.receipt_stages,
        node_results=node_results,
        unexpected_deselected=(),
        frontend_outcomes={
            "web_ui_test": "pass",
            "web_ui_build": "pass",
        },
        qualification=_qualification_receipt(plan, node_results),
        total_duration_ns=1000,
        general_recheck_observation_digest="sha256:" + "5" * 64,
        general_execution_observation_digest="sha256:" + "6" * 64,
    )

    verify_authoritative_receipt_documents(
        plan=plan,
        manifest=manifest,
        receipt=receipt,
        stage_documents=sequence.stage_documents,
        repo_root=REPOSITORY_ROOT,
        config=load_config(CONFIG_PATH),
        current_source_identity_digest=_source().digest,
        expected_authoritative=True,
    )
    assert receipt["terminal_status"] == "pass"
    assert receipt["authoritative"] is True
    assert receipt["admission_eligible"] is False
    assert receipt["live_eligible"] is False

    with pytest.raises(
        AuthoritativeRunnerError,
        match="crossed verifier domains",
    ):
        verify_authoritative_receipt_documents(
            plan=plan,
            manifest=manifest,
            receipt=receipt,
            stage_documents=sequence.stage_documents,
            repo_root=REPOSITORY_ROOT,
            config=load_config(CONFIG_PATH),
            current_source_identity_digest=_source().digest,
        )


@pytest.mark.parametrize("authoritative", (False, True))
def test_pure_candidate_verifier_reloads_raw_evidence_and_recomputes_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authoritative: bool,
) -> None:
    plan, manifest, receipt, _ = _green_receipt_fixture(
        tmp_path,
        authoritative=authoritative,
    )
    output_root = Path(plan["output_root"])
    plan_filename = (
        MAINLINE_AUTHORITATIVE_PLAN_FILENAME
        if authoritative
        else PLAN_FILENAME
    )
    receipt_filename = (
        MAINLINE_AUTHORITATIVE_RECEIPT_FILENAME
        if authoritative
        else MAINLINE_CANDIDATE_RECEIPT_FILENAME
    )
    (output_root / plan_filename).write_bytes(
        canonical_document_bytes(plan)
    )
    (output_root / NODE_MANIFEST_FILENAME).write_bytes(
        canonical_document_bytes(manifest)
    )
    (output_root / receipt_filename).write_bytes(
        canonical_document_bytes(receipt)
    )
    general_results = [
        dict(item)
        for item in receipt["coverage"]["node_results"]
        if item["owner"] == "general_non_live_pytest"
    ]
    qualification_results = [
        dict(item)
        for item in receipt["coverage"]["node_results"]
        if item["owner"] == "architecture_qualification_premerge"
    ]
    monkeypatch.setattr(
        authoritative_runner,
        "load_and_verify_general_recheck",
        lambda **_: receipt["coverage"][
            "general_recheck_observation_digest"
        ],
    )
    monkeypatch.setattr(
        authoritative_runner,
        "load_and_verify_general_execution",
        lambda **_: (
            general_results,
            receipt["coverage"]["general_execution_observation_digest"],
        ),
    )
    monkeypatch.setattr(
        authoritative_runner,
        "load_and_verify_qualification_sidecar",
        lambda **_: (
            qualification_results,
            receipt["qualification"],
        ),
    )
    monkeypatch.setattr(
        authoritative_runner,
        "verify_general_partition_bundle",
        lambda **_: {
            "merged_observation_digest": receipt["coverage"][
                "general_execution_observation_digest"
            ]
        },
    )

    verifier = (
        verify_authoritative_mainline_output
        if authoritative
        else verify_authoritative_candidate_output
    )
    result = verifier(
        output_root=output_root,
        repo_root=REPOSITORY_ROOT,
        config=load_config(CONFIG_PATH),
        current_source_identity_digest=_source().digest,
    )

    assert result.receipt["self_digest"] == receipt["self_digest"]
    assert result.plan["self_digest"] == plan["self_digest"]

    monkeypatch.setattr(
        authoritative_runner,
        "load_and_verify_general_execution",
        lambda **_: (general_results, "sha256:" + "f" * 64),
    )
    with pytest.raises(
        AuthoritativeRunnerError,
        match="general execution digest drifted",
    ):
        verifier(
            output_root=output_root,
            repo_root=REPOSITORY_ROOT,
            config=load_config(CONFIG_PATH),
            current_source_identity_digest=_source().digest,
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    (
        (
            lambda receipt: receipt["coverage"]["node_results"].pop(),
            "executed-node and result sets differ",
        ),
        (
            lambda receipt: receipt["coverage"][
                "unexpected_deselected"
            ].append("test_a.py::test_a"),
            "unexpected deselection",
        ),
        (
            lambda receipt: receipt["frontend"]["outcomes"].pop(
                "web_ui_build"
            ),
            "frontend outcomes are incomplete",
        ),
        (
            lambda receipt: receipt.update(
                {"invocation_id": "prior-invocation"}
            ),
            "plan or invocation binding drifted",
        ),
    ),
)
def test_receipt_verifier_rejects_incomplete_or_prior_evidence(
    tmp_path: Path,
    mutator: object,
    message: str,
) -> None:
    plan, manifest, receipt, stage_documents = _green_receipt_fixture(
        tmp_path
    )
    mutable = dict(receipt)
    mutable["coverage"] = dict(receipt["coverage"])
    mutable["coverage"]["node_results"] = [
        dict(item) for item in receipt["coverage"]["node_results"]
    ]
    mutable["coverage"]["unexpected_deselected"] = list(
        receipt["coverage"]["unexpected_deselected"]
    )
    mutable["frontend"] = {
        "required_stage_ids": list(
            receipt["frontend"]["required_stage_ids"]
        ),
        "outcomes": dict(receipt["frontend"]["outcomes"]),
    }
    mutator(mutable)
    tampered = _reseal(mutable)

    with pytest.raises(AuthoritativeRunnerError, match=message):
        verify_authoritative_receipt_documents(
            plan=plan,
            manifest=manifest,
            receipt=tampered,
            stage_documents=stage_documents,
            repo_root=REPOSITORY_ROOT,
            config=load_config(CONFIG_PATH),
        )


def test_receipt_verifier_rejects_missing_stage_output(
    tmp_path: Path,
) -> None:
    plan, manifest, receipt, stage_documents = _green_receipt_fixture(
        tmp_path
    )
    incomplete = dict(stage_documents)
    incomplete.pop("web_ui_build")
    with pytest.raises(AuthoritativeRunnerError, match="output document is missing"):
        verify_authoritative_receipt_documents(
            plan=plan,
            manifest=manifest,
            receipt=receipt,
            stage_documents=incomplete,
            repo_root=REPOSITORY_ROOT,
            config=load_config(CONFIG_PATH),
        )


def test_receipt_verifier_rejects_unknown_schema_digest_and_duplicate_node(
    tmp_path: Path,
) -> None:
    plan, manifest, receipt, stage_documents = _green_receipt_fixture(
        tmp_path
    )
    unknown_schema = dict(receipt)
    unknown_schema["schema_id"] = "openzyme_test_gate_receipt@999"
    unknown_schema.pop("self_digest")
    unknown_schema["self_digest"] = sha256_digest(
        canonical_json_bytes(unknown_schema)
    )
    with pytest.raises(
        AuthoritativeRunnerError,
        match="receipt is invalid",
    ):
        verify_authoritative_receipt_documents(
            plan=plan,
            manifest=manifest,
            receipt=unknown_schema,
            stage_documents=stage_documents,
            repo_root=REPOSITORY_ROOT,
            config=load_config(CONFIG_PATH),
        )

    corrupted_stages = dict(stage_documents)
    corrupted_stage = dict(corrupted_stages["web_ui_test"])
    corrupted_stage["stdout_tail"] = "digest drift"
    corrupted_stages["web_ui_test"] = corrupted_stage
    with pytest.raises(
        AuthoritativeRunnerError,
        match="document is invalid",
    ):
        verify_authoritative_receipt_documents(
            plan=plan,
            manifest=manifest,
            receipt=receipt,
            stage_documents=corrupted_stages,
            repo_root=REPOSITORY_ROOT,
            config=load_config(CONFIG_PATH),
        )

    duplicate = dict(receipt)
    duplicate["coverage"] = dict(receipt["coverage"])
    duplicate["coverage"]["node_results"] = [
        *[dict(item) for item in receipt["coverage"]["node_results"]],
        dict(receipt["coverage"]["node_results"][0]),
    ]
    duplicate = _reseal(duplicate)
    with pytest.raises(
        AuthoritativeRunnerError,
        match="duplicate node ids",
    ):
        verify_authoritative_receipt_documents(
            plan=plan,
            manifest=manifest,
            receipt=duplicate,
            stage_documents=stage_documents,
            repo_root=REPOSITORY_ROOT,
            config=load_config(CONFIG_PATH),
        )


def test_same_invocation_qualification_sidecar_closes_qh_qs_and_report(
    tmp_path: Path,
) -> None:
    from openzyme_host_api import (
        architecture_qualification_runner as qualification_runner,
    )

    plan, _, _ = _plan_fixture(tmp_path)
    output_root = Path(plan["output_root"])
    report_root = output_root / "qualification-report"
    report_root.mkdir()
    report_path = report_root / "architecture-qualification-report.json"
    report_path.write_text("{}\n", encoding="utf-8")
    qualification_stage = next(
        stage
        for stage in plan["stages"]
        if stage["stage_id"] == "architecture_qualification_premerge"
    )
    request = qualification_runner.MainlineQualificationSidecarRequest(
        output_path=output_root / "qualification-execution.json",
        invocation_id=plan["invocation_id"],
        plan_digest=plan["self_digest"],
        source_identity_digest=sha256_digest(
            canonical_json_bytes(plan["source_identity"])
        ),
        environment_digest=qualification_stage["environment_digest"],
    )

    def records(snapshot: dict[str, object]) -> list[dict[str, object]]:
        markers = {
            item["node_id"]: item["markers"]
            for item in snapshot["markers"]
        }
        return [
            {
                "duration_ns": 1,
                "markers": markers[node_id],
                "node_id": node_id,
                "outcome": "pass",
                "phases": [],
            }
            for node_id in snapshot["nodes"]
        ]

    sidecar_path = qualification_runner._publish_mainline_sidecar(  # noqa: SLF001
        repo_root=REPOSITORY_ROOT,
        request=request,
        mode="premerge_subset",
        report_path=report_path,
        report_payload_digest="sha256:" + "4" * 64,
        harness_records=records(
            plan["collections"]["qualification_harness"]
        ),
        scenario_records=records(
            plan["collections"]["qualification_scenarios"]
        ),
    )
    def report_verifier(*args: object) -> dict[str, object]:
        del args
        return {
            "payload_digest": "sha256:" + "4" * 64,
            "admission_eligible": False,
            "valid": True,
        }

    node_results, receipt_record = load_and_verify_qualification_sidecar(
        plan=plan,
        sidecar_path=sidecar_path,
        repo_root=REPOSITORY_ROOT,
        report_verifier=report_verifier,
    )
    assert [item["node_id"] for item in node_results] == [
        "test_b.py::test_b",
        "test_c.py::test_c",
    ]
    assert receipt_record["status"] == "verified"
    assert receipt_record["sidecar_digest"].startswith("sha256:")

    original_sidecar = sidecar_path.read_bytes()
    with pytest.raises(AuthoritativeRunnerError, match="sidecar is missing"):
        load_and_verify_qualification_sidecar(
            plan=plan,
            sidecar_path=sidecar_path.with_name("missing-sidecar.json"),
            repo_root=REPOSITORY_ROOT,
            report_verifier=report_verifier,
        )
    with pytest.raises(
        AuthoritativeRunnerError,
        match="report digest or authority boundary drifted",
    ):
        load_and_verify_qualification_sidecar(
            plan=plan,
            sidecar_path=sidecar_path,
            repo_root=REPOSITORY_ROOT,
            report_verifier=lambda *_: {
                "payload_digest": "sha256:" + "f" * 64,
                "admission_eligible": False,
                "valid": True,
            },
        )

    binding_drift = load_canonical_document_bytes(original_sidecar)
    binding_drift["environment_digest"] = "sha256:" + "e" * 64
    sidecar_path.write_bytes(
        canonical_document_bytes(_reseal(binding_drift))
    )
    with pytest.raises(
        AuthoritativeRunnerError,
        match="field 'environment_digest' drifted",
    ):
        load_and_verify_qualification_sidecar(
            plan=plan,
            sidecar_path=sidecar_path,
            repo_root=REPOSITORY_ROOT,
            report_verifier=report_verifier,
        )

    collection_drift = load_canonical_document_bytes(original_sidecar)
    collection_drift["harness_collection"].pop()
    sidecar_path.write_bytes(
        canonical_document_bytes(_reseal(collection_drift))
    )
    with pytest.raises(
        AuthoritativeRunnerError,
        match="harness_collection node set drifted",
    ):
        load_and_verify_qualification_sidecar(
            plan=plan,
            sidecar_path=sidecar_path,
            repo_root=REPOSITORY_ROOT,
            report_verifier=report_verifier,
        )

    sidecar_path.write_bytes(original_sidecar)
    tampered = load_canonical_document_bytes(sidecar_path.read_bytes())
    tampered["node_results"][0]["outcome"] = "skip"
    tampered = _reseal(tampered)
    sidecar_path.write_bytes(canonical_document_bytes(tampered))
    with pytest.raises(AuthoritativeRunnerError, match="not proven: skip"):
        load_and_verify_qualification_sidecar(
            plan=plan,
            sidecar_path=sidecar_path,
            repo_root=REPOSITORY_ROOT,
            report_verifier=report_verifier,
        )
