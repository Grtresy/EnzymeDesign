from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from test_gate.affected import (  # noqa: E402
    AffectedScopeError,
    ChangedPathInventory,
    EXPECTED_OWNER_ROOTS,
    collect_changed_path_inventory,
    expand_affected_scope,
    load_affected_scope_map,
)


MAP_PATH = REPOSITORY_ROOT / "scripts/test-affected-scope-map.json"


def _inventory(*paths: str) -> ChangedPathInventory:
    return ChangedPathInventory(
        base_ref="HEAD",
        base_commit="a" * 40,
        committed=tuple(sorted(paths)),
        staged=(),
        unstaged=(),
        relevant_untracked=(),
        paths=tuple(sorted(paths)),
    )


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(repo), *arguments),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def test_map_is_versioned_and_covers_every_current_owner() -> None:
    scope_map = load_affected_scope_map(MAP_PATH, repo_root=REPOSITORY_ROOT)

    assert scope_map.schema_id == "openzyme_test_affected_scope_map@1"
    assert scope_map.planner_id == "openzyme_test_diagnostic_planner@1"
    assert scope_map.required_owner_roots == EXPECTED_OWNER_ROOTS
    assert scope_map.digest.startswith("sha256:")
    for owner_root in EXPECTED_OWNER_ROOTS:
        changed_path = f"{owner_root}/src/example.py"
        matches = [
            rule for rule in scope_map.rules if rule.match_score(changed_path)
        ]
        assert matches, owner_root


def test_owner_local_source_uses_matching_test_and_explicit_frontend_omission() -> None:
    scope_map = load_affected_scope_map(MAP_PATH, repo_root=REPOSITORY_ROOT)

    selection = expand_affected_scope(
        REPOSITORY_ROOT,
        inventory=_inventory(
            "packages/openzyme-core/src/openzyme_core/agent_scheduler.py"
        ),
        scope_map=scope_map,
    )

    assert selection.matched_rules == ("openzyme-core-owner",)
    assert selection.pytest_paths == (
        "packages/openzyme-core/tests/test_agent_scheduler.py",
    )
    assert selection.lint_paths == ("packages/openzyme-core",)
    assert selection.frontend is False
    assert selection.fallback_complete_safe is False
    assert selection.as_plan_dict()["frontend"]["frontend_omission"] == (
        "diagnostic_only"
    )


def test_public_projection_and_ui_changes_include_frontend_contracts() -> None:
    scope_map = load_affected_scope_map(MAP_PATH, repo_root=REPOSITORY_ROOT)

    projection = expand_affected_scope(
        REPOSITORY_ROOT,
        inventory=_inventory(
            "packages/openzyme-core/src/openzyme_core/projections.py"
        ),
        scope_map=scope_map,
    )
    web_ui = expand_affected_scope(
        REPOSITORY_ROOT,
        inventory=_inventory("apps/openzyme-web-ui/src/view.js"),
        scope_map=scope_map,
    )

    assert projection.matched_rules == ("core-public-ui-contracts",)
    assert projection.frontend is True
    assert "apps/openzyme-host-api/tests/test_api.py" in projection.pytest_paths
    assert "packages/openzyme-core/tests/test_projections.py" in (
        projection.pytest_paths
    )
    assert web_ui.matched_rules == ("web-ui-owner",)
    assert web_ui.frontend is True
    assert web_ui.lint_paths == ()
    assert web_ui.pytest_paths == ()


@pytest.mark.parametrize(
    "changed_path",
    (
        "apps/openzyme-host-api/src/openzyme_host_api/app.py",
        "packages/openzyme-domain/src/openzyme_domain/control_plane.py",
        "packages/openzyme-core/src/openzyme_core/projections.py",
        "packages/openzyme-core/src/openzyme_core/controlled_operation_projection.py",
        "packages/openzyme-core/src/openzyme_core/runtime_command_projection.py",
        "packages/openzyme-core/src/openzyme_core/report_publication.py",
        "packages/openzyme-core/src/openzyme_core/artifact_projection.py",
        "packages/openzyme-core/src/openzyme_core/task_evidence.py",
        "packages/openzyme-runtime/src/openzyme_runtime/artifact_projection.py",
    ),
)
def test_public_ui_shape_families_have_exact_frontend_closure(
    changed_path: str,
) -> None:
    scope_map = load_affected_scope_map(MAP_PATH, repo_root=REPOSITORY_ROOT)

    selection = expand_affected_scope(
        REPOSITORY_ROOT,
        inventory=_inventory(changed_path),
        scope_map=scope_map,
    )

    assert selection.frontend is True
    assert selection.frontend_reason
    assert selection.as_plan_dict()["frontend"] == {
        "included": True,
        "stage_ids": ["web_ui_test", "web_ui_build"],
        "frontend_omission": None,
        "reason": selection.frontend_reason,
    }


@pytest.mark.parametrize(
    "changed_path",
    (
        "packages/openzyme-core/pyproject.toml",
        "packages/openzyme-core/src/openzyme_core/migrations/001_v3_control_plane_foundation.sql",
    ),
)
def test_dependency_metadata_and_migrations_expand_to_complete_safe_set(
    changed_path: str,
) -> None:
    scope_map = load_affected_scope_map(MAP_PATH, repo_root=REPOSITORY_ROOT)

    selection = expand_affected_scope(
        REPOSITORY_ROOT,
        inventory=_inventory(changed_path),
        scope_map=scope_map,
    )

    assert selection.fallback_complete_safe is True
    assert selection.pytest_paths == ("apps", "packages")
    assert selection.lint_paths == ("apps", "packages", "scripts")
    assert selection.frontend is True


def test_unknown_and_conflicting_paths_expand_to_complete_safe_set() -> None:
    scope_map = load_affected_scope_map(MAP_PATH, repo_root=REPOSITORY_ROOT)

    unknown = expand_affected_scope(
        REPOSITORY_ROOT,
        inventory=_inventory("mystery/unmapped.contract"),
        scope_map=scope_map,
    )
    conflicting_rule = replace(
        scope_map.rules[-1],
        id="conflicting-scripts-rule",
    )
    conflicting_map = replace(
        scope_map,
        rules=(*scope_map.rules, conflicting_rule),
    )
    conflict = expand_affected_scope(
        REPOSITORY_ROOT,
        inventory=_inventory("scripts/other-tool.py"),
        scope_map=conflicting_map,
    )

    for selection in (unknown, conflict):
        assert selection.fallback_complete_safe is True
        assert selection.lint_paths == ("apps", "packages", "scripts")
        assert selection.pytest_paths == ("apps", "packages")
        assert selection.frontend is True
        assert selection.fallback_reasons
    assert unknown.unknown_paths == ("mystery/unmapped.contract",)
    assert conflict.unknown_paths == ("scripts/other-tool.py",)


def test_documentation_only_rule_retains_nonempty_minimum_sanity() -> None:
    scope_map = load_affected_scope_map(MAP_PATH, repo_root=REPOSITORY_ROOT)

    selection = expand_affected_scope(
        REPOSITORY_ROOT,
        inventory=_inventory(
            "docs/v3/README.md",
            "openspec/changes/example/spec.md",
        ),
        scope_map=scope_map,
    )

    assert selection.matched_rules == (
        "documentation-and-spec-minimum-sanity",
    )
    assert selection.lint_paths
    assert selection.pytest_paths
    assert selection.frontend is False
    assert selection.fallback_complete_safe is False


def test_map_schema_planner_and_owner_drift_fail_closed(tmp_path: Path) -> None:
    payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    cases = (
        ("schema_id", "openzyme_test_affected_scope_map@2"),
        ("planner_id", "stale-planner@0"),
        ("required_owner_roots", payload["required_owner_roots"][:-1]),
    )
    for index, (field, value) in enumerate(cases):
        candidate = dict(payload)
        candidate[field] = value
        path = tmp_path / f"drift-{index}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(AffectedScopeError):
            load_affected_scope_map(path, repo_root=REPOSITORY_ROOT)


def test_change_inventory_combines_committed_staged_unstaged_and_untracked(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")

    (repo / "docs").mkdir()
    (repo / "docs/committed.md").write_text("committed\n", encoding="utf-8")
    _git(repo, "add", "docs/committed.md")
    _git(repo, "commit", "-qm", "committed")

    (repo / "packages").mkdir()
    (repo / "packages/staged.py").write_text("STAGED = True\n", encoding="utf-8")
    _git(repo, "add", "packages/staged.py")
    (repo / "README.md").write_text("unstaged\n", encoding="utf-8")
    (repo / "apps").mkdir()
    (repo / "apps/untracked.py").write_text("UNTRACKED = True\n", encoding="utf-8")
    (repo / "irrelevant.tmp").write_text("ignored\n", encoding="utf-8")

    inventory = collect_changed_path_inventory(repo, base_ref=base)

    assert inventory.base_commit == base
    assert inventory.committed == ("docs/committed.md",)
    assert inventory.staged == ("packages/staged.py",)
    assert inventory.unstaged == ("README.md",)
    assert inventory.relevant_untracked == ("apps/untracked.py",)
    assert inventory.paths == (
        "README.md",
        "apps/untracked.py",
        "docs/committed.md",
        "packages/staged.py",
    )


def test_invalid_base_and_empty_inventory_fail_explicitly(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "base")

    with pytest.raises(AffectedScopeError, match="cannot resolve"):
        collect_changed_path_inventory(repo, base_ref="missing-ref")
    scope_map = load_affected_scope_map(MAP_PATH, repo_root=REPOSITORY_ROOT)
    with pytest.raises(AffectedScopeError, match="inventory is empty"):
        expand_affected_scope(
            REPOSITORY_ROOT,
            inventory=_inventory(),
            scope_map=scope_map,
        )
