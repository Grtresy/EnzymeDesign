from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


OPERATOR_DIR = Path(__file__).resolve().parent


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test subject: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verifier = _load_module(
    "test_c2_agent_capability_lease_verifier",
    OPERATOR_DIR / "verify_agent_capability_lease.py",
)
sys.modules["verify_agent_capability_lease"] = verifier
generator = _load_module(
    "test_c2_agent_capability_lease_generator",
    OPERATOR_DIR / "generate_acceptance_receipt.py",
)
capture = _load_module(
    "test_c2_agent_capability_lease_capture",
    OPERATOR_DIR / "capture_final_evidence.py",
)


def _load(name: str) -> dict[str, Any]:
    value = verifier.load_document(name)
    assert value is not None
    return copy.deepcopy(value)


def _reseal(name: str, value: dict[str, Any]) -> None:
    _, digest_field = verifier.DOCUMENTS[name]
    value[digest_field] = verifier.digest_value(
        {key: item for key, item in value.items() if key != digest_field}
    )
    verifier.verify_document(name, value)


def _documents() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    names = ("prerequisites", "authority_matrix", "policy", "scope_boundary")
    documents = {name: _load(name) for name in names}
    digests = {
        name: verifier.verify_document(name, value)
        for name, value in documents.items()
    }
    return documents, digests


def _reseal_mainline_bindings(mainline: dict[str, Any]) -> None:
    source_identity = mainline["source_identity"]
    source_digest = verifier.digest_value(source_identity)
    mainline["source_identity_digest"] = source_digest
    mainline["receipt_source_identity_digest"] = source_digest

    plan = mainline["plan"]
    plan["source_identity"] = copy.deepcopy(source_identity)
    plan["toolchains"] = copy.deepcopy(source_identity["toolchains"])
    plan["self_digest"] = verifier.digest_value(
        {key: item for key, item in plan.items() if key != "self_digest"}
    )
    mainline["plan_digest"] = plan["self_digest"]
    mainline["receipt_plan_digest"] = plan["self_digest"]

    mainline_receipt = mainline["receipt"]
    mainline_receipt["plan_digest"] = plan["self_digest"]
    mainline_receipt["source_identity_digest"] = source_digest
    mainline_receipt["self_digest"] = verifier.digest_value(
        {
            key: item
            for key, item in mainline_receipt.items()
            if key != "self_digest"
        }
    )
    mainline["receipt_digest"] = mainline_receipt["self_digest"]
    verification_result = mainline["verification_result"]
    verification_result["plan_digest"] = plan["self_digest"]
    verification_result["receipt_digest"] = mainline_receipt["self_digest"]


def _valid_mainline() -> dict[str, Any]:
    c1_receipt = verifier.load_json_object(
        verifier.C1_OPERATOR_DIR / "acceptance-receipt.json"
    )
    mainline = copy.deepcopy(c1_receipt["mainline_validation"])
    mainline["source_identity"]["commit"] = verifier.BASELINE_REVISION
    _reseal_mainline_bindings(mainline)
    verifier._verify_mainline_evidence(mainline)
    return mainline


def _final_evidence_digest(receipt: dict[str, Any]) -> str:
    return verifier.digest_value(
        {
            "schema_id": verifier.FINAL_EVIDENCE_SCHEMA,
            "source_revision": receipt["source_revision"],
            "implementation_snapshot": receipt["implementation_snapshot"],
            "schema": receipt["schema"],
            "focused_validation": receipt["focused_validation"],
            "documentation": receipt["documentation"],
            "openspec_validation": receipt["openspec_validation"],
            "mainline_validation": receipt["mainline_validation"],
            "scope_audit": receipt["scope_audit"],
            "issued_at": receipt["issued_at"],
        }
    )


def _reseal_acceptance(receipt: dict[str, Any]) -> None:
    receipt["final_evidence_digest"] = _final_evidence_digest(receipt)
    receipt["receipt_digest"] = verifier.digest_value(
        {key: item for key, item in receipt.items() if key != "receipt_digest"}
    )


def _valid_acceptance() -> tuple[
    dict[str, Any], dict[str, dict[str, Any]], dict[str, str]
]:
    documents, document_digests = _documents()
    prerequisites = documents["prerequisites"]
    files: list[dict[str, Any]] = []
    implementation_tree_digest = verifier.digest_value(files)
    expected_scope_paths = sorted(
        [
            *verifier.EXPECTED_IMPLEMENTATION_PATHS,
            verifier.ACCEPTANCE_REPOSITORY_PATH,
        ]
    )
    expected_production_paths = sorted(
        path
        for path in verifier.EXPECTED_IMPLEMENTATION_PATHS
        if path.endswith(".py")
        and any(
            path.startswith(prefix)
            for prefix in verifier.PRODUCTION_SOURCE_PREFIXES
        )
    )
    receipt = {
        "schema_id": "agent_capability_lease_acceptance@1",
        "change_id": verifier.CHANGE_ID,
        "source_revision": verifier.BASELINE_REVISION,
        "c0_acceptance_receipt_digest": prerequisites["c0"]["receipt_digest"],
        "c1_acceptance_receipt_digest": prerequisites["c1"]["receipt_digest"],
        "prerequisite_bindings_digest": document_digests["prerequisites"],
        "authority_matrix_digest": document_digests["authority_matrix"],
        "capability_policy_document_digest": document_digests["policy"],
        "capability_policy_digest": documents["policy"]["lease_policy_digest"],
        "scope_boundary_digest": document_digests["scope_boundary"],
        "final_evidence_digest": "",
        "implementation_snapshot": {
            "file_count": 0,
            "files": files,
            "tree_digest": implementation_tree_digest,
        },
        "schema": {
            "sqlite_schema_before": 38,
            "sqlite_schema_after": 39,
            "migration_id": "039_v3_agent_capability_leases",
            "migration_sha256": verifier.digest_bytes(
                verifier.historical_migration_bytes()
            ),
            "lease_schema": "agent_capability_lease@1",
            "generation_reservation_schema": (
                "agent_workspace_generation_reservation@1"
            ),
            "retirement_request_schema": "agent_retirement_request@1",
            "retirement_cleanup_proof_schema": (
                "agent_retirement_cleanup_proof@1"
            ),
            "retirement_schema": "agent_retirement_record@1",
        },
        "focused_validation": {
            "status": "passed",
            "test_files": list(verifier.FOCUSED_TEST_FILES),
            "collection_command": [
                verifier.FOCUSED_PYTHON,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                *verifier.FOCUSED_TEST_FILES,
            ],
            "collection_exit_code": 0,
            "node_count": 1,
            "node_ids_digest": verifier.digest_value(["test::node"]),
            "collection_stdout_digest": verifier.digest_bytes(b"test::node\n"),
            "pytest_command": [
                verifier.FOCUSED_PYTHON,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--junitxml=/tmp/openzyme-c2-focused-test/focused-junit.xml",
                *verifier.FOCUSED_TEST_FILES,
            ],
            "pytest_exit_code": 0,
            "pytest_stdout_digest": verifier.digest_bytes(b"1 passed\n"),
            "passed": 1,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "ruff_command": [
                verifier.FOCUSED_PYTHON,
                "-m",
                "ruff",
                "check",
                *verifier.FOCUSED_RUFF_PATHS,
            ],
            "ruff_exit_code": 0,
            "ruff_stdout_digest": verifier.digest_bytes(b"All checks passed!\n"),
            "ruff_status": "passed",
            "environment": verifier.FOCUSED_ENVIRONMENT,
            "source_tree_digest": implementation_tree_digest,
            "live_provider_hpc_opt_in": False,
        },
        "documentation": {
            "status": "passed",
            "paths": list(verifier.DOCUMENTATION_PATHS),
        },
        "openspec_validation": {
            "status": "passed",
            "command": (
                "DO_NOT_TRACK=1 openspec validate "
                "establish-agent-capability-leases --type change --strict "
                "--no-interactive"
            ),
            "result": "Change 'establish-agent-capability-leases' is valid",
        },
        "mainline_validation": _valid_mainline(),
        "scope_audit": {
            "status": "passed",
            "changed_path_count": len(expected_scope_paths),
            "changed_path_set_digest": verifier.digest_value(expected_scope_paths),
            "implementation_manifest_digest": verifier.digest_value(
                list(verifier.EXPECTED_IMPLEMENTATION_PATHS)
            ),
            "forbidden_changed_paths": [],
            "ast_policy_digest": verifier.digest_value(
                verifier.deferred_ast_policy()
            ),
            "audited_production_paths": expected_production_paths,
            "audited_production_path_digest": verifier.digest_value(
                expected_production_paths
            ),
            "forbidden_findings": [],
        },
        "deferred_false_claims": copy.deepcopy(verifier.DEFERRED_FALSE_CLAIMS),
        "test_readiness_is_production_proof": False,
        "eligible_successor": {
            "short_name": "C3",
            "change_id": "provision-independent-agent-git-workspaces",
            "eligible_now": True,
        },
        "status": "passed",
        "issued_at": "test-only-not-production-evidence",
    }
    _reseal_acceptance(receipt)
    return receipt, documents, document_digests


def test_base_operator_boundary_passes_without_acceptance() -> None:
    result = verifier.verify_all(
        require_acceptance=False,
        verify_sources=False,
    )

    assert result["status"] == "passed"
    assert result["completed_tasks"] == 0
    assert result["external_effects"] == 0
    assert result["deferred_false_claims"] == verifier.DEFERRED_FALSE_CLAIMS
    assert result["test_readiness_is_production_proof"] is False
    assert result["eligible_successor"] == "C3_after_acceptance"


def test_document_digest_rejects_unsealed_tampering() -> None:
    policy = _load("policy")
    policy["profiles"]["general"].append("ssh")

    with pytest.raises(ValueError, match="canonical digest"):
        verifier.verify_document("policy", policy)


def test_prerequisite_rejects_resealed_c0_legacy_upgrade() -> None:
    binding = _load("prerequisites")
    binding["c0"]["legacy_decision"] = "legacy_go"
    _reseal("prerequisites", binding)

    with pytest.raises(ValueError, match="C0 prerequisite binding drifted"):
        verifier.verify_prerequisites(binding)


def test_prerequisite_rejects_resealed_c1_production_lease_claim() -> None:
    binding = _load("prerequisites")
    binding["c1"]["production_capability_lease_issuance_proven"] = True
    _reseal("prerequisites", binding)

    with pytest.raises(ValueError, match="C1 prerequisite binding drifted"):
        verifier.verify_prerequisites(binding)


def test_authority_matrix_rejects_resealed_cross_authority_substitution() -> None:
    matrix = _load("authority_matrix")
    matrix["cross_product"][0]["substitution"] = "allowed"
    _reseal("authority_matrix", matrix)

    with pytest.raises(ValueError, match="permits substitution"):
        verifier.verify_authority_matrix(matrix)


def test_authority_matrix_rejects_resealed_automatic_effect() -> None:
    matrix = _load("authority_matrix")
    matrix["automatic_effects"]["creates_controlled_operation_execution"] = True
    _reseal("authority_matrix", matrix)

    with pytest.raises(ValueError, match="forbidden automatic effect"):
        verifier.verify_authority_matrix(matrix)


def test_policy_rejects_resealed_general_profile_escalation() -> None:
    policy = _load("policy")
    policy["profiles"]["general"].append("ssh")
    _reseal("policy", policy)

    with pytest.raises(ValueError, match="closed general/executor"):
        verifier.verify_policy(policy)


def test_policy_rejects_resealed_host_destination_allowlist() -> None:
    policy = _load("policy")
    ordinary_network = policy["target_scope_policy"]["ordinary_network"]
    ordinary_network["host_destination_allowlist"] = True
    _reseal("policy", policy)

    with pytest.raises(ValueError, match="target-scope policy drifted"):
        verifier.verify_policy(policy)


def test_policy_rejects_resealed_credential_audience_widening() -> None:
    policy = _load("policy")
    ordinary_network = policy["target_scope_policy"]["ordinary_network"]
    ordinary_network["host_issued_credential_audience"] = "ambient"
    _reseal("policy", policy)

    with pytest.raises(ValueError, match="target-scope policy drifted"):
        verifier.verify_policy(policy)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (
            ("deferred_false_claims", "production_capsule_activation_proven"),
            True,
            "overclaims a deferred production proof",
        ),
        (
            ("test_readiness", "production_workspace_proof"),
            True,
            "promoted to production proof",
        ),
        (
            ("test_readiness", "may_clear_production_provisioning_required"),
            True,
            "promoted to production proof",
        ),
        (
            ("legacy_execution_noninterference", "may_act_as_fallback"),
            True,
            "used as a fallback",
        ),
    ],
)
def test_scope_rejects_resealed_false_production_claims(
    path: tuple[str, str],
    value: bool,
    message: str,
) -> None:
    scope = _load("scope_boundary")
    section, field = path
    scope[section][field] = value
    _reseal("scope_boundary", scope)

    with pytest.raises(ValueError, match=message):
        verifier.verify_scope_boundary(scope)


def test_scope_rejects_resealed_c3_successor_replacement() -> None:
    scope = _load("scope_boundary")
    scope["eligible_successor"]["short_name"] = "C4"
    _reseal("scope_boundary", scope)

    with pytest.raises(ValueError, match="successor boundary drifted"):
        verifier.verify_scope_boundary(scope)


def test_acceptance_rejects_resealed_deferred_production_overclaim() -> None:
    receipt, documents, document_digests = _valid_acceptance()
    verifier.verify_document("acceptance", receipt)
    verifier.verify_acceptance(
        receipt,
        documents,
        document_digests,
        verify_sources=False,
    )
    receipt["deferred_false_claims"][
        "production_agent_git_workspace_ready_proven"
    ] = True
    _reseal("acceptance", receipt)

    with pytest.raises(ValueError, match="overclaims a deferred production proof"):
        verifier.verify_acceptance(
            receipt,
            documents,
            document_digests,
            verify_sources=False,
        )


def test_acceptance_rejects_resealed_test_readiness_as_production_proof() -> None:
    receipt, documents, document_digests = _valid_acceptance()
    receipt["test_readiness_is_production_proof"] = True
    _reseal("acceptance", receipt)

    with pytest.raises(ValueError, match="promotes test readiness"):
        verifier.verify_acceptance(
            receipt,
            documents,
            document_digests,
            verify_sources=False,
        )


def test_acceptance_rejects_resealed_final_evidence_digest_substitution() -> None:
    receipt, documents, document_digests = _valid_acceptance()
    receipt["final_evidence_digest"] = verifier.digest_value({"forged": True})
    receipt["receipt_digest"] = verifier.digest_value(
        {key: item for key, item in receipt.items() if key != "receipt_digest"}
    )

    with pytest.raises(ValueError, match="reconstructed final evidence"):
        verifier.verify_acceptance(
            receipt,
            documents,
            document_digests,
            verify_sources=False,
        )


def test_acceptance_rejects_resealed_focused_pass_count_without_exact_nodes() -> None:
    receipt, documents, document_digests = _valid_acceptance()
    receipt["focused_validation"]["passed"] = 999
    _reseal_acceptance(receipt)

    with pytest.raises(ValueError, match="focused validation did not close"):
        verifier.verify_acceptance(
            receipt,
            documents,
            document_digests,
            verify_sources=False,
        )


def test_acceptance_rejects_resealed_focused_source_substitution() -> None:
    receipt, documents, document_digests = _valid_acceptance()
    receipt["focused_validation"]["source_tree_digest"] = verifier.digest_value(
        ["different source"]
    )
    _reseal_acceptance(receipt)

    with pytest.raises(ValueError, match="focused validation did not close"):
        verifier.verify_acceptance(
            receipt,
            documents,
            document_digests,
            verify_sources=False,
        )


def test_acceptance_rejects_embedded_mainline_plan_tamper() -> None:
    receipt, documents, document_digests = _valid_acceptance()
    receipt["mainline_validation"]["plan"]["worker_policy"]["workers"] = 999
    _reseal_acceptance(receipt)

    with pytest.raises(ValueError, match="mainline plan seal"):
        verifier.verify_acceptance(
            receipt,
            documents,
            document_digests,
            verify_sources=False,
        )


def test_acceptance_rejects_embedded_mainline_receipt_tamper() -> None:
    receipt, documents, document_digests = _valid_acceptance()
    receipt["mainline_validation"]["receipt"]["coverage"]["forged"] = True
    _reseal_acceptance(receipt)

    with pytest.raises(ValueError, match="mainline receipt seal"):
        verifier.verify_acceptance(
            receipt,
            documents,
            document_digests,
            verify_sources=False,
        )


def test_acceptance_rejects_resealed_truncated_configuration_identity() -> None:
    receipt, documents, document_digests = _valid_acceptance()
    mainline = receipt["mainline_validation"]
    mainline["source_identity"]["configurations"] = []
    _reseal_mainline_bindings(mainline)
    _reseal_acceptance(receipt)

    with pytest.raises(ValueError, match="configuration identity set drifted"):
        verifier.verify_acceptance(
            receipt,
            documents,
            document_digests,
            verify_sources=False,
        )


def test_working_tree_changed_paths_includes_staged_only_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=repository, check=True)
    subprocess.run(
        ("git", "config", "user.email", "test@example.invalid"),
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ("git", "config", "user.name", "C2 verifier test"),
        cwd=repository,
        check=True,
    )
    source = repository / "source.txt"
    source.write_text("before\n", encoding="utf-8")
    subprocess.run(("git", "add", "source.txt"), cwd=repository, check=True)
    subprocess.run(
        ("git", "commit", "-q", "-m", "baseline"),
        cwd=repository,
        check=True,
    )
    baseline = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source.write_text("after\n", encoding="utf-8")
    subprocess.run(("git", "add", "source.txt"), cwd=repository, check=True)
    assert subprocess.run(
        ("git", "diff", "--quiet"),
        cwd=repository,
        check=False,
    ).returncode == 0

    monkeypatch.setattr(verifier, "REPOSITORY_ROOT", repository)
    monkeypatch.setattr(verifier, "BASELINE_REVISION", baseline)

    assert verifier.working_tree_changed_paths() == ["source.txt"]


def test_scope_allowlist_distinguishes_exact_files_from_directories() -> None:
    assert verifier.is_allowed_scope_path("scripts/test-resource-manifest.json")
    assert verifier.is_allowed_scope_path(
        "packages/openzyme-core/src/openzyme_core/agent_capability_service.py"
    )
    assert not verifier.is_allowed_scope_path(
        "scripts/test-resource-manifest.json.unreviewed"
    )
    assert not verifier.is_allowed_scope_path("scripts/unreviewed.py")


def test_deferred_ast_audit_allows_closed_declaration_and_unavailable_port() -> None:
    source = b'''\
class UnavailableRemoteAgentCredentialIssuer:
    def issue(self) -> None:
        raise RuntimeError("remote credential provider is unavailable")

SLURM_OPERATIONS = "slurm_operations"
'''
    verifier.audit_added_production_ast(
        path="packages/openzyme-core/src/openzyme_core/declaration.py",
        content=source,
        added_lines=set(range(1, 8)),
    )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            b"class WorkspacePublicationIntent:\n    pass\n",
            "deferred owner symbol",
        ),
        (
            b"import subprocess\nsubprocess.run(['git', 'clone'])\n",
            "deferred effect call",
        ),
        (
            b"def run(runner):\n    runner.sbatch()\n",
            "deferred effect call",
        ),
        (
            b"@app.post('/jobs')\ndef submit_job():\n    pass\n",
            "deferred product route",
        ),
        (
            b"import asyncssh\n",
            "deferred implementation import",
        ),
    ],
)
def test_deferred_ast_audit_rejects_successor_implementation(
    source: bytes,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        verifier.audit_added_production_ast(
            path="packages/openzyme-core/src/openzyme_core/forbidden.py",
            content=source,
            added_lines=set(range(1, source.count(b"\n") + 2)),
        )


def test_capture_executes_strict_openspec_with_telemetry_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def run(argv: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=f"{capture.OPEN_SPEC_RESULT}\n",
            stderr="",
        )

    monkeypatch.setattr(capture.subprocess, "run", run)

    assert capture._openspec_validation() == {
        "status": "passed",
        "command": capture.OPEN_SPEC_COMMAND,
        "result": capture.OPEN_SPEC_RESULT,
    }
    assert observed["argv"] == (
        "openspec",
        "validate",
        verifier.CHANGE_ID,
        "--type",
        "change",
        "--strict",
        "--no-interactive",
    )
    assert observed["kwargs"]["check"] is True
    assert observed["kwargs"]["env"]["DO_NOT_TRACK"] == "1"


def test_capture_executes_exact_focused_collection_pytest_and_ruff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def run(argv: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed.append((argv, kwargs))
        if "--collect-only" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="tests/test_one.py::test_one\ntests/test_two.py::test_two\n",
                stderr="",
            )
        if "pytest" in argv:
            junit_argument = next(
                argument for argument in argv if argument.startswith("--junitxml=")
            )
            Path(junit_argument.removeprefix("--junitxml=")).write_text(
                '<testsuites><testsuite tests="2" failures="0" errors="0" '
                'skipped="0" /></testsuites>',
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="2 passed in 0.01s\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="All checks passed!\n",
            stderr="",
        )

    monkeypatch.setattr(capture.subprocess, "run", run)

    result = capture._run_focused_validation(
        source_tree_digest=verifier.digest_value([])
    )

    assert result["passed"] == 2
    assert result["node_count"] == 2
    assert result["node_ids_digest"] == verifier.digest_value(
        ["tests/test_one.py::test_one", "tests/test_two.py::test_two"]
    )
    assert result["ruff_stdout_digest"] == verifier.digest_bytes(
        b"All checks passed!\n"
    )
    assert len(observed) == 3
    assert all(
        call[1]["env"]["PYTHONDONTWRITEBYTECODE"] == "1" for call in observed
    )


def test_final_mode_requires_absent_acceptance_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        verifier.DOCUMENTS,
        "acceptance",
        ("missing-acceptance-receipt.json", "receipt_digest"),
    )

    with pytest.raises(ValueError, match="acceptance-receipt.json"):
        verifier.verify_all(
            require_acceptance=True,
            verify_sources=False,
        )


def _pending_tasks_path(tmp_path: Path) -> Path:
    tasks = verifier.C2_TASKS_PATH.read_text(encoding="utf-8")
    tasks = tasks.replace("- [x] 1.1 ", "- [ ] 1.1 ", 1)
    assert "- [ ] 1.1 " in tasks
    path = tmp_path / "pending-tasks.md"
    path.write_text(tasks, encoding="utf-8")
    return path


def test_task_gate_rejects_pending_checklist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verifier, "C2_TASKS_PATH", _pending_tasks_path(tmp_path))
    with pytest.raises(ValueError, match="checklist remains incomplete"):
        verifier.verify_tasks()


def test_generator_refuses_to_build_before_task_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verifier, "C2_TASKS_PATH", _pending_tasks_path(tmp_path))
    with pytest.raises(ValueError, match="checklist remains incomplete"):
        generator.build_acceptance_receipt({})


def test_capture_refuses_to_build_before_task_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verifier, "C2_TASKS_PATH", _pending_tasks_path(tmp_path))
    with pytest.raises(ValueError, match="checklist remains incomplete"):
        capture.build_final_evidence(
            mainline_root=tmp_path,
            issued_at="test-only-not-production-evidence",
        )
