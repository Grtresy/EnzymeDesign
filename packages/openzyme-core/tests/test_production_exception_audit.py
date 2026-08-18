from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

from openzyme_core.repositories import _mutation_write_allowed


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUDIT_SCRIPT = REPOSITORY_ROOT / "scripts" / "audit-production-exceptions.py"


def _load_audit_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "openzyme_production_exception_audit",
        AUDIT_SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_current_cutover_production_exception_audit_is_clean_and_deterministic() -> None:
    audit = _load_audit_module()

    first = audit.build_report(REPOSITORY_ROOT)
    second = audit.build_report(REPOSITORY_ROOT)

    assert first == second
    assert first["violations"] == []
    assert first["scan_errors"] == []
    assert first["broad_handlers"]
    assert first["outside_scope_claimed_clean"] is False
    assert first["deployment_mutation_authorized"] is False


def test_audit_rejects_bare_silent_and_unchained_broad_catches(tmp_path: Path) -> None:
    audit = _load_audit_module()
    source = tmp_path / "boundary.py"
    source.write_text(
        """
def bare():
    try:
        operation()
    except:
        pass

def silent():
    try:
        operation()
    except Exception:
        return None

def unchained():
    try:
        operation()
    except Exception as exc:
        raise RuntimeError(str(exc))
""".lstrip(),
        encoding="utf-8",
    )
    tree = __import__("ast").parse(source.read_text(encoding="utf-8"))
    parents = {
        child: node
        for node in __import__("ast").walk(tree)
        for child in __import__("ast").iter_child_nodes(node)
    }
    violations = []
    for handler in (
        node
        for node in __import__("ast").walk(tree)
        if isinstance(node, __import__("ast").ExceptHandler)
    ):
        function = audit._qualified_function(handler, parents)
        violations.extend(
            audit._handler_violations(
                path="boundary.py",
                handler=handler,
                function=function,
            )
        )

    assert {item["rule"] for item in violations} == {
        "bare_except",
        "cause_not_chained",
        "unrecorded_broad_catch",
    }


def test_sqlite_mutation_callback_fails_closed_without_raising() -> None:
    class BrokenSessionIdentity:
        def __str__(self) -> str:
            raise RuntimeError("conversion exploded")

    assert (
        _mutation_write_allowed(
            None,
            session_id=BrokenSessionIdentity(),
            resource_category="task",
        )
        == 0
    )
