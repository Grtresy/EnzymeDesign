from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUDIT_SCRIPT = REPOSITORY_ROOT / "scripts" / "audit-v3-compat-callers.py"


def _load_audit_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "openzyme_retired_surface_audit", AUDIT_SCRIPT
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture_root(tmp_path: Path) -> Path:
    files = {
        "apps/openzyme-host-cli/pyproject.toml": (
            "[project]\nname='cli'\nversion='0.0.0'\n"
            "[project.scripts]\nopenzyme='example:main'\n"
        ),
        "apps/mcp-hpc-runner/pyproject.toml": (
            "[project]\nname='runner'\nversion='0.0.0'\n"
            "[project.scripts]\nmcp-hpc-runner='example:main'\n"
        ),
        "apps/example/src/example/__init__.py": (
            "CURRENT_CONTRACT = 'file_workspace_public@2'\n"
        ),
        "packages/example/src/example/__init__.py": "CURRENT_SCHEMA = 'final@2'\n",
        "packages/openzyme-store-sqlite/src/openzyme_store_sqlite/migrations/"
        "001_file_workspace_final.sql": (
            "CREATE TABLE files (file_id TEXT PRIMARY KEY);\n"
        ),
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def test_current_retired_surface_audit_is_clean_and_deterministic() -> None:
    audit = _load_audit_module()

    first = audit.build_report(REPOSITORY_ROOT)
    second = audit.build_report(REPOSITORY_ROOT)

    assert first == second
    assert first["violations"] == []
    assert first["scan_errors"] == []
    assert first["repository_only"] is True
    assert first["deployment_removal_authorized"] is False


def test_audit_rejects_a_retired_callable_surface(tmp_path: Path) -> None:
    audit = _load_audit_module()
    root = _fixture_root(tmp_path)
    source = root / "apps/example/src/example/consumer.py"
    source.write_text("TOOL = 'execution.pipeline.start'\n", encoding="utf-8")

    report = audit.build_report(root)

    assert any(
        item["rule"] == "retired_callable_surface"
        and item["path"] == "apps/example/src/example/consumer.py"
        for item in report["violations"]
    )


def test_audit_rejects_a_legacy_entrypoint_alias(tmp_path: Path) -> None:
    audit = _load_audit_module()
    root = _fixture_root(tmp_path)
    cli = root / "apps/openzyme-host-cli/pyproject.toml"
    cli.write_text(
        "[project]\nname='cli'\nversion='0.0.0'\n"
        "[project.scripts]\nopenzyme='example:main'\nenzyme='example:main'\n",
        encoding="utf-8",
    )

    report = audit.build_report(root)

    assert any(item["rule"] == "entrypoint_set_drift" for item in report["violations"])


def test_audit_does_not_treat_split_negative_guard_as_a_callable_surface(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    root = _fixture_root(tmp_path)
    source = root / "packages/example/src/example/guard.py"
    source.write_text("RETIRED = 'arti' + 'fact.'\n", encoding="utf-8")

    report = audit.build_report(root)

    assert report["violations"] == []
