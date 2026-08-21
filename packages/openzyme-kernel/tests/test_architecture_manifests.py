from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
CHECK_PATH = ROOT / "scripts" / "check-openzyme-architecture.py"
BASELINE_PATH = ROOT / "docs/v3/architecture/source-bound-baseline.json"
TABLE_OWNER_PATH = ROOT / "docs/v3/architecture/table-owner-manifest.json"


def _load_check_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "openzyme_architecture_check",
        CHECK_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_bound_architecture_manifests_are_current() -> None:
    completed = subprocess.run(
        [sys.executable, str(CHECK_PATH)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert result["component_count"] == len(baseline["expected_component_ids"])
    assert result["component_inventory_digest"] == (
        baseline["component_inventory_digest"]
    )
    assert result["import_graph_digest"] == baseline["import_graph_digest"]
    table_owner = json.loads(TABLE_OWNER_PATH.read_text(encoding="utf-8"))
    assert result["counts"] == table_owner["expected_object_counts"]


def test_table_owner_manifest_rejects_multiple_or_missing_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_check_module()
    component_ids = {
        item["component_id"]
        for item in module.observe_component_inventory()["components"]
    }
    original = json.loads(module.TABLE_OWNER_PATH.read_text(encoding="utf-8"))

    duplicate = json.loads(json.dumps(original))
    duplicate["semantic_owner_rules"].append(
        {
            "rule_id": "duplicate-session-owner",
            "target_owner": "openzyme.kernel",
            "prefixes": [],
            "exact_names": ["sessions"],
        }
    )
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(json.dumps(duplicate), encoding="utf-8")
    monkeypatch.setattr(module, "TABLE_OWNER_PATH", duplicate_path)
    with pytest.raises(module.ArchitectureCheckError, match="has 2 semantic owners"):
        module.validate_table_owners(component_ids, enforce_digest=False)

    orphan = json.loads(json.dumps(original))
    kernel_rule = next(
        item
        for item in orphan["semantic_owner_rules"]
        if item["rule_id"] == "kernel-control-plane"
    )
    kernel_rule["exact_names"].remove("sessions")
    orphan_path = tmp_path / "orphan.json"
    orphan_path.write_text(json.dumps(orphan), encoding="utf-8")
    monkeypatch.setattr(module, "TABLE_OWNER_PATH", orphan_path)
    with pytest.raises(module.ArchitectureCheckError, match="has 0 semantic owners"):
        module.validate_table_owners(component_ids, enforce_digest=False)


def test_traceability_registry_rejects_stale_source_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_check_module()
    component_ids = {
        item["component_id"]
        for item in module.observe_component_inventory()["components"]
    }
    registry = json.loads(module.TRACEABILITY_PATH.read_text(encoding="utf-8"))
    registry["entries"][0]["source_refs"][0] = "missing/source.py"
    registry_path = tmp_path / "traceability.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(module, "TRACEABILITY_PATH", registry_path)

    with pytest.raises(module.ArchitectureCheckError, match="stale path"):
        module.validate_traceability(component_ids)


def test_component_dependency_policy_rejects_reverse_and_distribution_edges() -> None:
    module = _load_check_module()
    inventory = module.observe_component_inventory()

    reverse = copy.deepcopy(inventory)
    kernel = next(
        item
        for item in reverse["components"]
        if item["component_id"] == "openzyme.kernel"
    )
    kernel["dependencies"].append("openzyme-research")
    with pytest.raises(
        module.ArchitectureCheckError,
        match="forbidden component dependency",
    ):
        module.validate_component_boundaries(reverse)

    semantic_standard = copy.deepcopy(inventory)
    compute = next(
        item
        for item in semantic_standard["components"]
        if item["component_id"] == "openzyme.compute"
    )
    compute["dependencies"].append("openzyme-standard")
    with pytest.raises(
        module.ArchitectureCheckError,
        match="forbidden component dependency|semantic dependency",
    ):
        module.validate_component_boundaries(semantic_standard)


def test_component_kind_and_source_policy_reject_invalid_authority() -> None:
    module = _load_check_module()
    inventory = module.observe_component_inventory()
    component_kinds = {
        item["component_id"]: item["component_kind"]
        for item in inventory["components"]
    }
    component_kinds["openzyme.store.sqlite"] = "plugin"
    with pytest.raises(
        module.ArchitectureCheckError,
        match="Adapter slot has wrong component kind",
    ):
        module._validate_distribution_scaffolds(
            set(component_kinds),
            component_kinds=component_kinds,
        )

    policy = json.loads(
        module.COMPONENT_BOUNDARY_POLICY_PATH.read_text(encoding="utf-8")
    )
    with pytest.raises(
        module.ArchitectureCheckError,
        match="Adapter declares an Agent tool",
    ):
        module.validate_component_source_policy(
            "openzyme.store.sqlite",
            "adapter",
            "ToolContribution(owner_plugin_id='not-allowed')",
            policy,
            source_label="<adapter-negative>",
        )
    with pytest.raises(
        module.ArchitectureCheckError,
        match="forbidden source vocabulary",
    ):
        module.validate_component_source_policy(
            "openzyme.kernel",
            "kernel",
            "# hidden HMMER policy branch",
            policy,
            source_label="<kernel-negative>",
        )
    module.validate_component_source_policy(
        "openzyme.kernel",
        "kernel",
        "KERNEL_FORBIDDEN_TOOL_NAMES = {'hmmer'}",
        policy,
        source_label="<kernel-declaration-positive>",
    )
    with pytest.raises(
        module.ArchitectureCheckError,
        match="canonical-state implementation",
    ):
        module.validate_component_source_policy(
            "openzyme.standard",
            "distribution",
            "import sqlite3",
            policy,
            source_label="<distribution-negative>",
        )


def test_kernel_source_has_no_concrete_adapter_or_plugin_dependency() -> None:
    source_root = ROOT / "packages/openzyme-kernel/src/openzyme_kernel"
    forbidden_import_roots = {
        "openzyme_compute",
        "openzyme_hpc",
        "openzyme_process_podman",
        "openzyme_reporting",
        "openzyme_research",
        "openzyme_runtime_llm",
        "openzyme_science",
        "openzyme_store_sqlite",
        "openzyme_workspace_git_lfs",
    }
    forbidden_stdlib_mechanisms = {"sqlite3", "subprocess"}
    violations: list[str] = []

    for source_path in sorted(source_root.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        forbidden = sorted(
            imported.intersection(forbidden_import_roots | forbidden_stdlib_mechanisms)
        )
        if forbidden:
            violations.append(f"{source_path.name}: {', '.join(forbidden)}")

    assert violations == []


def test_historical_roots_and_unregistered_shims_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_check_module()
    inventory = module.observe_component_inventory()
    historical = copy.deepcopy(inventory)
    historical["components"][0]["path"] = "legacy/reintroduced-component"
    with pytest.raises(
        module.ArchitectureCheckError,
        match="historical component",
    ):
        module.validate_historical_path_exclusion(historical)

    ledger = json.loads(module.REEXPORT_LEDGER_PATH.read_text(encoding="utf-8"))
    ledger["entries"] = [{"symbol": "SecondAuthority"}]
    ledger_path = tmp_path / "reexports.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    monkeypatch.setattr(module, "REEXPORT_LEDGER_PATH", ledger_path)
    with pytest.raises(
        module.ArchitectureCheckError,
        match="retired temporary re-export ledger entries must be empty",
    ):
        module.validate_reexport_ledger()
