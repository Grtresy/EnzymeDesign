from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any
from typing import Callable

import pytest


MODULE_PATH = Path(__file__).with_name("verify_repository_binding.py")
SPEC = importlib.util.spec_from_file_location("verify_repository_binding", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(repository: Path, path: str, content: str) -> None:
    target = repository / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


@pytest.fixture
def isolated_git_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.name", "C1 verifier test")
    _git(repository, "config", "user.email", "c1-verifier@example.test")
    _write(repository, "src/implementation.py", "VALUE = 'baseline'\n")
    _write(repository, "docs/架构.md", "baseline\n")
    _write(repository, "mainline.toml", "profile = 'test'\n")
    _write(repository, "test.lock", "locked\n")
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", "baseline")

    monkeypatch.setattr(VERIFIER, "REPOSITORY_ROOT", repository)
    monkeypatch.setattr(
        VERIFIER, "BASELINE_REVISION", _git(repository, "rev-parse", "HEAD")
    )
    monkeypatch.setattr(
        VERIFIER,
        "ACCEPTANCE_REPOSITORY_PATH",
        "operator/acceptance-receipt.json",
    )
    monkeypatch.setattr(
        VERIFIER,
        "MAINLINE_CONFIGURATION_PATHS",
        ("mainline.toml",),
    )
    monkeypatch.setattr(VERIFIER, "MAINLINE_LOCK_PATHS", ("test.lock",))
    return repository


def _toolchains() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "executable": f"/test/bin/{name}",
            "version": f"{name} test version",
            "available": True,
        }
        for name in ("python", "node", "uv", "npm")
    ]


def _current_source_identity() -> dict[str, Any]:
    changed = VERIFIER.working_tree_changed_paths()
    tracked_at_baseline = set(
        VERIFIER._git_output(
            "-c",
            "core.quotePath=false",
            "ls-tree",
            "-r",
            "--name-only",
            VERIFIER.BASELINE_REVISION,
        )
        .decode("utf-8")
        .splitlines()
    )
    tracked = sorted(path for path in changed if path in tracked_at_baseline)
    untracked = sorted(
        path
        for path in changed
        if path not in tracked_at_baseline
        and path != VERIFIER.ACCEPTANCE_REPOSITORY_PATH
    )
    diff_arguments = [
        "diff",
        "--binary",
        "--no-ext-diff",
        "--no-textconv",
        VERIFIER.BASELINE_REVISION,
        "--",
        *tracked,
    ]
    return {
        "commit": VERIFIER.BASELINE_REVISION,
        "tracked_diff_digest": VERIFIER.digest_bytes(
            VERIFIER._git_output(*diff_arguments)
        ),
        "tracked_dirty_paths": tracked,
        "relevant_untracked_sources": [
            VERIFIER._snapshot_file_identity(path, None) for path in untracked
        ],
        "configurations": [
            VERIFIER._snapshot_file_identity(path, None)
            for path in VERIFIER.MAINLINE_CONFIGURATION_PATHS
        ],
        "locks": [
            VERIFIER._snapshot_file_identity(path, None)
            for path in VERIFIER.MAINLINE_LOCK_PATHS
        ],
        "toolchains": _toolchains(),
    }


def _receipt_with_source_identity(source_identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "mainline_validation": {
            "source_identity": source_identity,
            "source_identity_digest": VERIFIER.digest_value(source_identity),
        }
    }


def _mainline_evidence() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    source_identity = {
        "commit": VERIFIER.BASELINE_REVISION,
        "tracked_diff_digest": f"sha256:{'1' * 64}",
        "tracked_dirty_paths": [],
        "relevant_untracked_sources": [],
        "configurations": [
            {
                "path": path,
                "kind": "missing",
                "mode": None,
                "size": None,
                "digest": None,
            }
            for path in VERIFIER.MAINLINE_CONFIGURATION_PATHS
        ],
        "locks": [
            {
                "path": path,
                "kind": "missing",
                "mode": None,
                "size": None,
                "digest": None,
            }
            for path in VERIFIER.MAINLINE_LOCK_PATHS
        ],
        "toolchains": _toolchains(),
    }
    output_root = "/tmp/c1-mainline-evidence"
    plan = {
        "authority": {
            "admission_eligible": False,
            "authoritative": True,
            "authority_domain": "authoritative_non_live_mainline",
            "current_authoritative_entry": "scripts/check-mainline.sh",
            "live_eligible": False,
            "profile_contract_authoritative": True,
        },
        "collections": [],
        "config_digest": f"sha256:{'2' * 64}",
        "expected_coverage_digest": f"sha256:{'3' * 64}",
        "invocation_id": "c1-verifier-test",
        "legacy_execution_multiset_digest": f"sha256:{'4' * 64}",
        "node_ownership": {},
        "output_root": output_root,
        "planner_digest": f"sha256:{'5' * 64}",
        "profile_id": "mainline_authoritative",
        "schema_id": "openzyme_test_execution_plan@1",
        "source_identity": source_identity,
        "source_recheck_policy": {},
        "stages": [],
        "toolchains": source_identity["toolchains"],
        "worker_policy": {},
    }
    plan["self_digest"] = VERIFIER.digest_value(plan)
    source_identity_digest = VERIFIER.digest_value(source_identity)
    receipt = {
        "admission_eligible": False,
        "authoritative": True,
        "coverage": {},
        "frontend": {},
        "invocation_id": "c1-verifier-test",
        "live_eligible": False,
        "plan_digest": plan["self_digest"],
        "profile_id": "mainline_authoritative",
        "qualification": {},
        "resource_assignments": [],
        "schema_id": "openzyme_test_gate_receipt@1",
        "source_identity_digest": source_identity_digest,
        "stages": [],
        "terminal_status": "pass",
        "timing": {},
    }
    receipt["self_digest"] = VERIFIER.digest_value(receipt)
    verification = {
        "profile_id": "mainline_authoritative",
        "output_root": output_root,
        "plan_digest": plan["self_digest"],
        "receipt_digest": receipt["self_digest"],
        "terminal_status": "pass",
        "valid": True,
        "authoritative": True,
        "profile_contract_authoritative": True,
        "admission_eligible": False,
        "live_eligible": False,
        "authority_domain": "authoritative_non_live_mainline",
        "current_authoritative_entry": "scripts/check-mainline.sh",
    }
    return plan, receipt, verification


def _acceptance_context() -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    names = (
        "baseline",
        "policy",
        "binding",
        "preflight",
        "standard_protocol",
        "local_protocol",
        "restore",
    )
    documents = {name: VERIFIER.load_document(name) for name in names}
    digests = {
        name: VERIFIER.verify_document(name, document)
        for name, document in documents.items()
    }
    documents["c0"] = VERIFIER.load_c0_acceptance()
    return documents, digests


def _valid_acceptance() -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    documents, digests = _acceptance_context()
    plan, mainline_receipt, verification = _mainline_evidence()
    source_identity = plan["source_identity"]
    preflight = documents["preflight"]
    binding = documents["binding"]
    database = preflight["preflight"]["database"]
    root_facts = preflight["preflight"]["root_facts"]
    acceptance = {
        "schema_id": "project_repository_binding_acceptance@1",
        "change_id": VERIFIER.CHANGE_ID,
        "source_revision": VERIFIER.BASELINE_REVISION,
        "c0_acceptance_receipt_digest": documents["c0"]["receipt_digest"],
        "implementation_baseline_digest": digests["baseline"],
        "durable_root_preflight_digest": digests["preflight"],
        "standard_protocol_implementation_digest": digests["standard_protocol"],
        "local_protocol_acceptance_digest": digests["local_protocol"],
        "restore_rehearsal_digest": digests["restore"],
        "implementation_snapshot": {
            "file_count": 0,
            "files": [],
            "tree_digest": VERIFIER.digest_value([]),
        },
        "schema": {
            "sqlite_schema_before": 37,
            "sqlite_schema_after": 38,
            "migration_id": "038_v3_project_repository_bindings",
            "migration_sha256": VERIFIER.digest_bytes(
                (VERIFIER.REPOSITORY_ROOT / VERIFIER.MIGRATION_PATH).read_bytes()
            ),
            "binding_schema": "project_repository_binding@1",
            "session_pin_schema": "session_repository_binding_pin@1",
            "credential_schema": "repository_credential@1",
        },
        "configuration": {
            "acceptance_profile": "approved_local_development",
            "https_origin": preflight["https_origin"],
            "database_identity_digest": preflight["database_identity_digest"],
            "database_mode": database["mode"],
            "binding_inventory_digest": preflight["preflight"]["inventory_digest"],
            "repository_policy_digest": digests["policy"],
            "binding_canonical_digest": binding["canonical_digest"],
            "durable_root_path_digests": sorted(
                str(item["path_digest"]) for item in root_facts
            ),
            "all_required_settings_explicit": True,
            "credential_material_projected": False,
            "upstream_authority": "separate_controlled_external_operation",
        },
        "scope_audit": {
            "status": "passed",
            "changed_path_count": 1,
            "changed_path_set_digest": VERIFIER.digest_value(
                [VERIFIER.ACCEPTANCE_REPOSITORY_PATH]
            ),
            "forbidden_changed_paths": [],
        },
        "focused_tests": {
            "status": "passed",
            "test_files": list(VERIFIER.FOCUSED_TEST_FILES),
            "passed": 3,
            "failed": 0,
        },
        "native_integration": {
            "status": "passed",
            "test_file": (
                "apps/openzyme-host-api/tests/test_repository_native_clients.py"
            ),
            "passed": 3,
            "failed": 0,
            "git_smart_http_v2_over_https": True,
            "git_lfs_batch_v2_basic": True,
            "durable_restart_reread": True,
            "revoked_credential_rejected": True,
            "hostile_git_environment_isolated": True,
            "multi_ref_push_rejected": True,
            "dynamic_health_verified": True,
            "closed_namespace_write_rejected": True,
            "released_lease_hold_write_rejected": True,
        },
        "documentation": {
            "status": "passed",
            "paths": list(VERIFIER.DOCUMENTATION_PATHS),
        },
        "forbidden_pattern_audit": {
            "status": "passed",
            "catch_all_matches": [],
            "silent_fallback_matches": [],
            "ambient_git_fallback_matches": [],
        },
        "openspec_validation": {
            "status": "passed",
            "command": (
                "DO_NOT_TRACK=1 openspec validate "
                "establish-project-repository-bindings --type change --strict "
                "--no-interactive"
            ),
        },
        "mainline_validation": {
            "status": "passed",
            "command": "./scripts/check-mainline.sh",
            "verification_command": "verify-mainline-authoritative",
            "profile_id": "mainline_authoritative",
            "authority_domain": "authoritative_non_live_mainline",
            "current_authoritative_entry": "scripts/check-mainline.sh",
            "plan_digest": plan["self_digest"],
            "receipt_digest": mainline_receipt["self_digest"],
            "source_identity_digest": VERIFIER.digest_value(source_identity),
            "source_identity": source_identity,
            "plan_schema_id": plan["schema_id"],
            "receipt_schema_id": mainline_receipt["schema_id"],
            "receipt_plan_digest": mainline_receipt["plan_digest"],
            "receipt_source_identity_digest": mainline_receipt[
                "source_identity_digest"
            ],
            "verification_result": verification,
            "plan": plan,
            "receipt": mainline_receipt,
            "terminal_status": "pass",
            "authoritative": True,
            "profile_contract_authoritative": True,
            "admission_eligible": False,
            "live_eligible": False,
            "verified_current_sources": True,
        },
        "product_boundaries": {
            "agent_clone_provisioning_implemented": False,
            "workspace_publication_implemented": False,
            "production_capability_lease_issuance_proven": False,
            "production_disaster_recovery_proven": False,
            "upstream_effects": 0,
        },
        "eligible_successor": {
            "change": "provision-independent-agent-git-workspaces",
            "condition": ("establish-agent-capability-leases acceptance also passes"),
            "eligible_now": False,
        },
        "status": "passed",
        "issued_at": "2026-08-16T00:00:00+00:00",
    }
    acceptance["receipt_digest"] = VERIFIER.digest_value(acceptance)
    return acceptance, documents, digests


def _reseal_acceptance(acceptance: dict[str, Any]) -> None:
    acceptance["receipt_digest"] = VERIFIER.digest_value(
        {key: value for key, value in acceptance.items() if key != "receipt_digest"}
    )


def _verify_acceptance_only(acceptance: dict[str, Any]) -> None:
    _, documents, digests = _valid_acceptance()
    VERIFIER.verify_document("acceptance", acceptance)
    VERIFIER.verify_acceptance(acceptance, documents, digests)


def _operator_copy(tmp_path: Path) -> Path:
    operator_dir = tmp_path / "operator"
    operator_dir.mkdir()
    for name in (
        "baseline",
        "policy",
        "binding",
        "preflight",
        "standard_protocol",
        "local_protocol",
        "restore",
    ):
        filename, _ = VERIFIER.DOCUMENTS[name]
        shutil.copy2(MODULE_PATH.with_name(filename), operator_dir / filename)
    return operator_dir


def _rewrite_document(
    operator_dir: Path,
    name: str,
    mutate: Callable[[dict[str, Any]], None],
    *,
    close_digest: bool = True,
) -> None:
    filename, digest_field = VERIFIER.DOCUMENTS[name]
    path = operator_dir / filename
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    if close_digest:
        if digest_field is None:
            raise ValueError("test helper cannot add a digest field to this document")
        preimage = {
            key: value for key, value in document.items() if key != digest_field
        }
        document[digest_field] = VERIFIER.digest_value(preimage)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _verify_from(operator_dir: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(VERIFIER, "OPERATOR_DIR", operator_dir)
    return VERIFIER.verify_all(require_acceptance=False, verify_sources=False)


def test_complete_c1_operator_evidence_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _verify_from(_operator_copy(tmp_path), monkeypatch)
    assert result["status"] == "passed"
    assert result["upstream_effects"] == 0
    assert result["production_capability_lease_issuance_proven"] is False
    assert result["production_disaster_recovery_proven"] is False


def test_canonical_receipt_tamper_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    _rewrite_document(
        operator_dir,
        "standard_protocol",
        lambda document: document["implementation"].update({"git": "custom_file_rpc"}),
        close_digest=False,
    )
    with pytest.raises(ValueError, match="canonical digest does not match"):
        _verify_from(operator_dir, monkeypatch)


def test_forbidden_local_directory_fallback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    _rewrite_document(
        operator_dir,
        "standard_protocol",
        lambda document: document["forbidden_fallbacks"].update(
            {"local_directory_remote": True}
        ),
    )
    with pytest.raises(ValueError, match="forbidden fallback"):
        _verify_from(operator_dir, monkeypatch)


def test_acceptance_only_lease_cannot_claim_production_issuance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    _rewrite_document(
        operator_dir,
        "local_protocol",
        lambda document: document["credential_authority"].update(
            {"production_capability_lease_issuance_proven": True}
        ),
    )
    with pytest.raises(ValueError, match="overclaims production lease issuance"):
        _verify_from(operator_dir, monkeypatch)


def test_same_filesystem_rehearsal_cannot_claim_production_dr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    _rewrite_document(
        operator_dir,
        "restore",
        lambda document: document.update({"production_disaster_recovery_proven": True}),
    )
    with pytest.raises(ValueError, match="falsely claims production disaster recovery"):
        _verify_from(operator_dir, monkeypatch)


def test_missing_standard_protocol_receipt_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    (operator_dir / VERIFIER.DOCUMENTS["standard_protocol"][0]).unlink()
    with pytest.raises(ValueError, match="required operator document is missing"):
        _verify_from(operator_dir, monkeypatch)


def test_final_acceptance_cannot_skip_current_source_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    monkeypatch.setattr(VERIFIER, "OPERATOR_DIR", operator_dir)
    with pytest.raises(
        ValueError,
        match="final C1 acceptance requires current source verification",
    ):
        VERIFIER.verify_all(require_acceptance=True, verify_sources=False)


def test_final_acceptance_receipt_is_required_with_source_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_dir = _operator_copy(tmp_path)
    monkeypatch.setattr(VERIFIER, "OPERATOR_DIR", operator_dir)
    with pytest.raises(ValueError, match="acceptance-receipt.json"):
        VERIFIER.verify_all(require_acceptance=True, verify_sources=True)


def test_baseline_relative_diff_includes_staged_implementation(
    isolated_git_repository: Path,
) -> None:
    _write(
        isolated_git_repository,
        "src/implementation.py",
        "VALUE = 'staged implementation'\n",
    )
    _git(isolated_git_repository, "add", "src/implementation.py")

    changed = VERIFIER.working_tree_changed_paths()
    assert "src/implementation.py" in changed
    source_identity = _current_source_identity()
    VERIFIER._verify_mainline_source_identity(
        _receipt_with_source_identity(source_identity),
        revision=None,
        changed=changed,
    )


def test_baseline_relative_diff_preserves_non_ascii_tracked_path(
    isolated_git_repository: Path,
) -> None:
    _write(isolated_git_repository, "docs/架构.md", "current\n")

    changed = VERIFIER.working_tree_changed_paths()
    assert "docs/架构.md" in changed
    source_identity = _current_source_identity()
    assert "docs/架构.md" in source_identity["tracked_dirty_paths"]
    VERIFIER._verify_mainline_source_identity(
        _receipt_with_source_identity(source_identity),
        revision=None,
        changed=changed,
    )


def test_staged_non_acceptance_file_added_after_mainline_is_rejected(
    isolated_git_repository: Path,
) -> None:
    _write(
        isolated_git_repository,
        "src/implementation.py",
        "VALUE = 'mainline implementation'\n",
    )
    _git(isolated_git_repository, "add", "src/implementation.py")
    mainline_source_identity = _current_source_identity()

    _write(
        isolated_git_repository,
        "src/post_mainline.py",
        "VALUE = 'stale mainline'\n",
    )
    _git(isolated_git_repository, "add", "src/post_mainline.py")
    changed = VERIFIER.working_tree_changed_paths()
    assert "src/post_mainline.py" in changed

    with pytest.raises(ValueError, match="untracked source set drifted"):
        VERIFIER._verify_mainline_source_identity(
            _receipt_with_source_identity(mainline_source_identity),
            revision=None,
            changed=changed,
        )


def test_staged_acceptance_only_addition_preserves_mainline_identity(
    isolated_git_repository: Path,
) -> None:
    _write(
        isolated_git_repository,
        "src/implementation.py",
        "VALUE = 'mainline implementation'\n",
    )
    _git(isolated_git_repository, "add", "src/implementation.py")
    mainline_source_identity = _current_source_identity()

    _write(
        isolated_git_repository,
        VERIFIER.ACCEPTANCE_REPOSITORY_PATH,
        "{}\n",
    )
    _git(
        isolated_git_repository,
        "add",
        VERIFIER.ACCEPTANCE_REPOSITORY_PATH,
    )
    changed = VERIFIER.working_tree_changed_paths()
    assert VERIFIER.ACCEPTANCE_REPOSITORY_PATH in changed

    VERIFIER._verify_mainline_source_identity(
        _receipt_with_source_identity(mainline_source_identity),
        revision=None,
        changed=changed,
    )


@pytest.mark.parametrize(
    ("group", "message"),
    (
        ("configurations", "configuration identity set drifted"),
        ("locks", "lock identity set drifted"),
        ("toolchains", "toolchain identity set drifted"),
    ),
)
def test_mainline_identity_rejects_truncated_authoritative_sets(
    isolated_git_repository: Path,
    group: str,
    message: str,
) -> None:
    _write(
        isolated_git_repository,
        "src/implementation.py",
        "VALUE = 'mainline implementation'\n",
    )
    _git(isolated_git_repository, "add", "src/implementation.py")
    source_identity = _current_source_identity()
    source_identity[group] = []

    with pytest.raises(ValueError, match=message):
        VERIFIER._verify_mainline_source_identity(
            _receipt_with_source_identity(source_identity),
            revision=None,
            changed=VERIFIER.working_tree_changed_paths(),
        )


def test_valid_embedded_mainline_evidence_passes() -> None:
    acceptance, _, _ = _valid_acceptance()
    _verify_acceptance_only(acceptance)


def test_embedded_mainline_plan_self_digest_tamper_is_rejected() -> None:
    acceptance, _, _ = _valid_acceptance()
    acceptance["mainline_validation"]["plan"]["worker_policy"] = {"tampered": True}
    _reseal_acceptance(acceptance)

    with pytest.raises(ValueError, match="mainline plan seal is invalid"):
        _verify_acceptance_only(acceptance)


def test_embedded_mainline_receipt_self_digest_tamper_is_rejected() -> None:
    acceptance, _, _ = _valid_acceptance()
    acceptance["mainline_validation"]["receipt"]["timing"] = {"tampered": True}
    _reseal_acceptance(acceptance)

    with pytest.raises(ValueError, match="mainline receipt seal is invalid"):
        _verify_acceptance_only(acceptance)


def test_embedded_mainline_receipt_plan_binding_tamper_is_rejected() -> None:
    acceptance, _, _ = _valid_acceptance()
    mainline = acceptance["mainline_validation"]
    mainline_receipt = mainline["receipt"]
    tampered_plan_digest = f"sha256:{'9' * 64}"
    mainline_receipt["plan_digest"] = tampered_plan_digest
    mainline_receipt["self_digest"] = VERIFIER.digest_value(
        {key: value for key, value in mainline_receipt.items() if key != "self_digest"}
    )
    mainline["receipt_plan_digest"] = tampered_plan_digest
    mainline["receipt_digest"] = mainline_receipt["self_digest"]
    mainline["verification_result"]["receipt_digest"] = mainline_receipt["self_digest"]
    _reseal_acceptance(acceptance)

    with pytest.raises(ValueError, match="does not bind the exact plan"):
        _verify_acceptance_only(acceptance)


def test_old_green_mainline_cannot_be_replayed_for_new_source_identity() -> None:
    acceptance, _, _ = _valid_acceptance()
    mainline = acceptance["mainline_validation"]
    replayed_source_identity = deepcopy(mainline["source_identity"])
    replayed_source_identity["tracked_dirty_paths"] = ["replayed/source.py"]
    replayed_digest = VERIFIER.digest_value(replayed_source_identity)
    mainline["source_identity"] = replayed_source_identity
    mainline["source_identity_digest"] = replayed_digest
    mainline["receipt_source_identity_digest"] = replayed_digest
    _reseal_acceptance(acceptance)

    with pytest.raises(ValueError, match="mainline plan binding drifted"):
        _verify_acceptance_only(acceptance)
