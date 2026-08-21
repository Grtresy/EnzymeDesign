"""Versioned affected-scope change inventory and fail-safe dependency expansion."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any, Callable, Mapping

from .config import TestGateConfig
from .diagnostic import (
    DIAGNOSTIC_PLANNER_ID,
    DiagnosticRunResult,
    _planner_digest,
    _run_diagnostic,
)
from .model import canonical_json_bytes, sha256_digest
from .runner import ProcessResult, run_command
from .shadow import assert_source_stable
from .source import (
    SourceIdentity,
    collect_source_identity,
    is_relevant_untracked_path,
)

AFFECTED_SCOPE_MAP_SCHEMA_ID = "openzyme_test_affected_scope_map@1"
DEFAULT_AFFECTED_SCOPE_MAP_PATH = (
    Path(__file__).resolve().parents[1] / "test-affected-scope-map.json"
)
EXPECTED_OWNER_ROOTS = (
    "apps/mcp-hpc-runner",
    "apps/openzyme-host-api",
    "apps/openzyme-host-cli",
    "apps/openzyme-web-ui",
    "packages/enzymedesign-alphafold",
    "packages/enzymedesign-aox",
    "packages/enzymedesign-aox-executor",
    "packages/enzymedesign-bio-provider-adapters",
    "packages/enzymedesign-bio-providers",
    "packages/enzymedesign-core",
    "packages/enzymedesign-distribution",
    "packages/enzymedesign-docking-preprocess",
    "packages/enzymedesign-hmmer",
    "packages/enzymedesign-sequence-toolpack",
    "packages/enzymedesign-structure",
    "packages/enzymedesign-vina",
    "packages/openzyme-client",
    "packages/openzyme-compute",
    "packages/openzyme-contracts",
    "packages/openzyme-execution-contracts",
    "packages/openzyme-execution-sdk",
    "packages/openzyme-extension-spi",
    "packages/openzyme-hpc",
    "packages/openzyme-hpc-slurm",
    "packages/openzyme-hpc-ssh",
    "packages/openzyme-kernel",
    "packages/openzyme-process-podman",
    "packages/openzyme-reporting",
    "packages/openzyme-research",
    "packages/openzyme-research-tavily",
    "packages/openzyme-runtime-llm",
    "packages/openzyme-runtime-spi",
    "packages/openzyme-science",
    "packages/openzyme-science-research",
    "packages/openzyme-standard",
    "packages/openzyme-store-sqlite",
    "packages/openzyme-workspace-git-lfs",
)


class AffectedScopeError(RuntimeError):
    """Raised when changed-path or dependency-map closure fails."""


@dataclass(frozen=True)
class SelectionTemplate:
    lint_paths: tuple[str, ...]
    pytest_paths: tuple[str, ...]
    frontend: bool
    reason: str


@dataclass(frozen=True)
class AffectedRule:
    id: str
    paths: tuple[str, ...]
    prefixes: tuple[str, ...]
    lint_paths: tuple[str, ...]
    pytest_paths: tuple[str, ...]
    owner_test_root: str | None
    matching_tests: bool
    frontend: bool
    mode: str
    reason: str

    def match_score(self, path: str) -> int | None:
        if path in self.paths:
            return 1_000_000 + len(path)
        scores = [len(prefix) for prefix in self.prefixes if path.startswith(prefix)]
        return max(scores, default=None)


@dataclass(frozen=True)
class AffectedScopeMap:
    path: Path
    digest: str
    schema_id: str
    planner_id: str
    complete_safe: SelectionTemplate
    minimum_sanity: SelectionTemplate
    required_owner_roots: tuple[str, ...]
    rules: tuple[AffectedRule, ...]


@dataclass(frozen=True)
class ChangedPathInventory:
    base_ref: str
    base_commit: str
    committed: tuple[str, ...]
    staged: tuple[str, ...]
    unstaged: tuple[str, ...]
    relevant_untracked: tuple[str, ...]
    paths: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "base_ref": self.base_ref,
            "base_commit": self.base_commit,
            "committed": list(self.committed),
            "staged": list(self.staged),
            "unstaged": list(self.unstaged),
            "relevant_untracked": list(self.relevant_untracked),
            "paths": list(self.paths),
        }


@dataclass(frozen=True)
class AffectedSelection:
    inventory: ChangedPathInventory
    map_digest: str
    lint_paths: tuple[str, ...]
    pytest_paths: tuple[str, ...]
    matched_rules: tuple[str, ...]
    path_rules: tuple[tuple[str, str], ...]
    unknown_paths: tuple[str, ...]
    fallback_complete_safe: bool
    fallback_reasons: tuple[str, ...]
    frontend: bool
    frontend_reason: str

    def as_plan_dict(self) -> dict[str, object]:
        return {
            "input": {
                "lint_paths": [],
                "pytest_paths": [],
                "node_ids": [],
                "contract_groups": [],
                "changed_paths": list(self.inventory.paths),
                "base_ref": self.inventory.base_ref,
                "base_commit": self.inventory.base_commit,
                "change_sources": {
                    "committed": list(self.inventory.committed),
                    "staged": list(self.inventory.staged),
                    "unstaged": list(self.inventory.unstaged),
                    "relevant_untracked": list(
                        self.inventory.relevant_untracked
                    ),
                },
            },
            "expanded": {
                "lint_paths": list(self.lint_paths),
                "pytest_selectors": list(self.pytest_paths),
                "collection_selectors": list(self.pytest_paths),
            },
            "matched_rules": list(self.matched_rules),
            "path_rules": [
                {"path": path, "rule_id": rule_id}
                for path, rule_id in self.path_rules
            ],
            "unknown_paths": list(self.unknown_paths),
            "map_digest": self.map_digest,
            "fallback_complete_safe": self.fallback_complete_safe,
            "fallback_reasons": list(self.fallback_reasons),
            "collection_deselection_policy": (
                "exclude_declared_non_live_markers"
            ),
            "policy_deselected_nodes": [],
            "frontend": {
                "included": self.frontend,
                "stage_ids": (
                    ["web_ui_test", "web_ui_build"] if self.frontend else []
                ),
                "frontend_omission": (
                    None if self.frontend else "diagnostic_only"
                ),
                "reason": self.frontend_reason,
            },
        }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AffectedScopeError(f"affected map duplicates JSON key {key!r}")
        result[key] = value
    return result


def _closed(
    value: Any,
    *,
    fields: set[str],
    context: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise AffectedScopeError(
            f"{context} must contain exactly {sorted(fields)!r}"
        )
    return value


def _string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise AffectedScopeError(f"{context} must be a nonempty string")
    return value


def _strings(value: Any, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AffectedScopeError(f"{context} must be an array")
    result = tuple(_string(item, context=f"{context}[]") for item in value)
    if len(result) != len(set(result)):
        raise AffectedScopeError(f"{context} contains duplicates")
    return tuple(sorted(result))


def _boolean(value: Any, *, context: str) -> bool:
    if type(value) is not bool:
        raise AffectedScopeError(f"{context} must be a boolean")
    return value


def _template(value: Any, *, context: str) -> SelectionTemplate:
    raw = _closed(
        value,
        fields={"lint_paths", "pytest_paths", "frontend", "reason"},
        context=context,
    )
    return SelectionTemplate(
        lint_paths=_strings(raw["lint_paths"], context=f"{context}.lint_paths"),
        pytest_paths=_strings(
            raw["pytest_paths"],
            context=f"{context}.pytest_paths",
        ),
        frontend=_boolean(raw["frontend"], context=f"{context}.frontend"),
        reason=_string(raw["reason"], context=f"{context}.reason"),
    )


def _rule(value: Any, *, index: int) -> AffectedRule:
    context = f"rules[{index}]"
    raw = _closed(
        value,
        fields={
            "id",
            "paths",
            "prefixes",
            "lint_paths",
            "pytest_paths",
            "owner_test_root",
            "matching_tests",
            "frontend",
            "mode",
            "reason",
        },
        context=context,
    )
    owner_test_root = raw["owner_test_root"]
    if owner_test_root is not None:
        owner_test_root = _string(
            owner_test_root,
            context=f"{context}.owner_test_root",
        )
    mode = _string(raw["mode"], context=f"{context}.mode")
    if mode not in {"mapped", "minimum_sanity", "complete_safe"}:
        raise AffectedScopeError(f"{context}.mode is unsupported: {mode!r}")
    paths = _strings(raw["paths"], context=f"{context}.paths")
    prefixes = _strings(raw["prefixes"], context=f"{context}.prefixes")
    if not paths and not prefixes:
        raise AffectedScopeError(f"{context} must match at least one path or prefix")
    matching_tests = _boolean(
        raw["matching_tests"],
        context=f"{context}.matching_tests",
    )
    if matching_tests and owner_test_root is None:
        raise AffectedScopeError(
            f"{context}.matching_tests requires owner_test_root"
        )
    return AffectedRule(
        id=_string(raw["id"], context=f"{context}.id"),
        paths=paths,
        prefixes=prefixes,
        lint_paths=_strings(
            raw["lint_paths"],
            context=f"{context}.lint_paths",
        ),
        pytest_paths=_strings(
            raw["pytest_paths"],
            context=f"{context}.pytest_paths",
        ),
        owner_test_root=owner_test_root,
        matching_tests=matching_tests,
        frontend=_boolean(raw["frontend"], context=f"{context}.frontend"),
        mode=mode,
        reason=_string(raw["reason"], context=f"{context}.reason"),
    )


def _assert_repository_selector(
    repo_root: Path,
    selector: str,
    *,
    context: str,
) -> None:
    pure = PurePosixPath(selector)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise AffectedScopeError(f"{context} is not repository-relative: {selector!r}")
    try:
        resolved = (repo_root / selector).resolve(strict=True)
    except OSError as exc:
        raise AffectedScopeError(f"{context} does not exist: {selector!r}") from exc
    try:
        inside = os.path.commonpath((str(repo_root), str(resolved))) == str(
            repo_root
        )
    except ValueError as exc:
        raise AffectedScopeError(f"cannot validate {context}: {selector!r}") from exc
    if not inside:
        raise AffectedScopeError(f"{context} escapes the repository: {selector!r}")


def load_affected_scope_map(
    path: Path = DEFAULT_AFFECTED_SCOPE_MAP_PATH,
    *,
    repo_root: Path,
) -> AffectedScopeMap:
    """Strictly load and validate the versioned affected-scope map."""

    try:
        content = path.read_bytes()
        parsed = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AffectedScopeError(f"invalid affected-scope map {path}: {exc}") from exc
    root = _closed(
        parsed,
        fields={
            "schema_id",
            "planner_id",
            "complete_safe",
            "minimum_sanity",
            "required_owner_roots",
            "rules",
        },
        context="affected-scope map",
    )
    schema_id = _string(root["schema_id"], context="schema_id")
    planner_id = _string(root["planner_id"], context="planner_id")
    if schema_id != AFFECTED_SCOPE_MAP_SCHEMA_ID:
        raise AffectedScopeError(
            f"affected map schema drifted: {schema_id!r}"
        )
    if planner_id != DIAGNOSTIC_PLANNER_ID:
        raise AffectedScopeError(
            f"affected map planner identity drifted: {planner_id!r}"
        )
    required_owner_roots = _strings(
        root["required_owner_roots"],
        context="required_owner_roots",
    )
    if required_owner_roots != EXPECTED_OWNER_ROOTS:
        raise AffectedScopeError(
            "affected map required_owner_roots does not cover every current owner"
        )
    raw_rules = root["rules"]
    if not isinstance(raw_rules, list) or not raw_rules:
        raise AffectedScopeError("affected map rules must be a nonempty array")
    rules = tuple(_rule(value, index=index) for index, value in enumerate(raw_rules))
    if len(rules) != len({rule.id for rule in rules}):
        raise AffectedScopeError("affected map rule ids must be unique")
    covered_owner_roots = {
        prefix.removesuffix("/")
        for rule in rules
        for prefix in rule.prefixes
        if prefix.removesuffix("/") in EXPECTED_OWNER_ROOTS
    }
    if covered_owner_roots != set(EXPECTED_OWNER_ROOTS):
        missing = sorted(set(EXPECTED_OWNER_ROOTS) - covered_owner_roots)
        raise AffectedScopeError(
            "affected map lacks owner prefix rule(s): " + ", ".join(missing)
        )
    resolved_root = repo_root.resolve(strict=True)
    complete_safe = _template(root["complete_safe"], context="complete_safe")
    minimum_sanity = _template(
        root["minimum_sanity"],
        context="minimum_sanity",
    )
    selectors = [
        *complete_safe.lint_paths,
        *complete_safe.pytest_paths,
        *minimum_sanity.lint_paths,
        *minimum_sanity.pytest_paths,
    ]
    for rule in rules:
        selectors.extend(rule.lint_paths)
        selectors.extend(rule.pytest_paths)
        if rule.owner_test_root is not None:
            selectors.append(rule.owner_test_root)
    for selector in sorted(set(selectors)):
        _assert_repository_selector(
            resolved_root,
            selector,
            context="affected map selector",
        )
    return AffectedScopeMap(
        path=path.resolve(strict=True),
        digest=sha256_digest(content),
        schema_id=schema_id,
        planner_id=planner_id,
        complete_safe=complete_safe,
        minimum_sanity=minimum_sanity,
        required_owner_roots=required_owner_roots,
        rules=rules,
    )


def _run_git(repo_root: Path, *arguments: str) -> bytes:
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    try:
        result = subprocess.run(
            ("git", "-C", str(repo_root), *arguments),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AffectedScopeError(
            f"cannot execute git {' '.join(arguments)}: {exc}"
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise AffectedScopeError(
            f"git {' '.join(arguments)} failed with {result.returncode}: "
            f"{stderr[-2000:]}"
        )
    return result.stdout


def _decode_paths(content: bytes, *, context: str) -> tuple[str, ...]:
    if not content:
        return ()
    values = content.split(b"\0")
    if values[-1] == b"":
        values.pop()
    try:
        decoded = [value.decode("utf-8") for value in values]
    except UnicodeDecodeError as exc:
        raise AffectedScopeError(f"{context} contains a non-UTF-8 path") from exc
    normalized: list[str] = []
    for value in decoded:
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise AffectedScopeError(
                f"{context} contains an unsafe path: {value!r}"
            )
        canonical = pure.as_posix()
        if canonical != value:
            raise AffectedScopeError(
                f"{context} contains a noncanonical path: {value!r}"
            )
        normalized.append(value)
    return tuple(sorted(set(normalized)))


def collect_changed_path_inventory(
    repo_root: Path,
    *,
    base_ref: str,
) -> ChangedPathInventory:
    """Combine base/HEAD, staged, unstaged, and relevant untracked paths."""

    if not isinstance(base_ref, str) or not base_ref or base_ref.startswith("-"):
        raise AffectedScopeError("affected scope requires an explicit safe base ref")
    root = repo_root.resolve(strict=True)
    try:
        base_commit = _run_git(
            root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{base_ref}^{{commit}}",
        ).strip().decode("ascii")
    except (UnicodeDecodeError, AffectedScopeError) as exc:
        raise AffectedScopeError(
            f"cannot resolve affected-scope base ref {base_ref!r}"
        ) from exc
    committed = _decode_paths(
        _run_git(
            root,
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            base_commit,
            "HEAD",
            "--",
        ),
        context="committed diff",
    )
    staged = _decode_paths(
        _run_git(
            root,
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "--no-renames",
            "--",
        ),
        context="staged diff",
    )
    unstaged = _decode_paths(
        _run_git(
            root,
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            "--",
        ),
        context="unstaged diff",
    )
    relevant_untracked = tuple(
        path
        for path in _decode_paths(
            _run_git(
                root,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ),
            context="untracked inventory",
        )
        if is_relevant_untracked_path(path)
    )
    paths = tuple(
        sorted(
            {
                *committed,
                *staged,
                *unstaged,
                *relevant_untracked,
            }
        )
    )
    return ChangedPathInventory(
        base_ref=base_ref,
        base_commit=base_commit,
        committed=committed,
        staged=staged,
        unstaged=unstaged,
        relevant_untracked=relevant_untracked,
        paths=paths,
    )


def _matching_owner_test(
    repo_root: Path,
    *,
    changed_path: str,
    owner_test_root: str,
) -> str:
    test_prefix = f"{owner_test_root.rstrip('/')}/"
    if changed_path.startswith(test_prefix) and changed_path.endswith(".py"):
        if (repo_root / changed_path).is_file():
            return changed_path
        return owner_test_root
    if not changed_path.endswith(".py"):
        return owner_test_root
    stem = PurePosixPath(changed_path).stem
    candidate = f"{owner_test_root.rstrip('/')}/test_{stem}.py"
    if (repo_root / candidate).is_file():
        return candidate
    return owner_test_root


def expand_affected_scope(
    repo_root: Path,
    *,
    inventory: ChangedPathInventory,
    scope_map: AffectedScopeMap,
) -> AffectedSelection:
    """Expand changed paths through the map, broadening on every unknown."""

    if not inventory.paths:
        raise AffectedScopeError(
            "affected-scope changed path inventory is empty"
        )
    root = repo_root.resolve(strict=True)
    lint_paths: set[str] = set()
    pytest_paths: set[str] = set()
    matched_rules: set[str] = set()
    path_rules: list[tuple[str, str]] = []
    unknown_paths: list[str] = []
    fallback_reasons: list[str] = []
    frontend = False
    frontend_reasons: set[str] = set()
    minimum_sanity_used = False

    for changed_path in inventory.paths:
        scored = [
            (score, rule)
            for rule in scope_map.rules
            if (score := rule.match_score(changed_path)) is not None
        ]
        if not scored:
            unknown_paths.append(changed_path)
            fallback_reasons.append(f"unknown changed path: {changed_path}")
            continue
        best_score = max(score for score, _ in scored)
        best_rules = [rule for score, rule in scored if score == best_score]
        if len(best_rules) != 1:
            unknown_paths.append(changed_path)
            fallback_reasons.append(
                f"conflicting affected-map rules for {changed_path}: "
                + ", ".join(sorted(rule.id for rule in best_rules))
            )
            continue
        rule = best_rules[0]
        matched_rules.add(rule.id)
        path_rules.append((changed_path, rule.id))
        if rule.mode == "complete_safe":
            fallback_reasons.append(
                f"{rule.id} requires complete safe expansion: {changed_path}"
            )
            continue
        if rule.mode == "minimum_sanity":
            minimum_sanity_used = True
            continue
        lint_paths.update(rule.lint_paths)
        pytest_paths.update(rule.pytest_paths)
        if rule.matching_tests and rule.owner_test_root is not None:
            pytest_paths.add(
                _matching_owner_test(
                    root,
                    changed_path=changed_path,
                    owner_test_root=rule.owner_test_root,
                )
            )
        if rule.frontend:
            frontend = True
            frontend_reasons.add(rule.reason)

    fallback_complete_safe = bool(fallback_reasons)
    if fallback_complete_safe:
        lint_paths = set(scope_map.complete_safe.lint_paths)
        pytest_paths = set(scope_map.complete_safe.pytest_paths)
        frontend = scope_map.complete_safe.frontend
        frontend_reason = scope_map.complete_safe.reason
    else:
        if minimum_sanity_used:
            lint_paths.update(scope_map.minimum_sanity.lint_paths)
            pytest_paths.update(scope_map.minimum_sanity.pytest_paths)
            frontend = frontend or scope_map.minimum_sanity.frontend
        frontend_reason = (
            "; ".join(sorted(frontend_reasons))
            if frontend
            else (
                "diagnostic-only omission proven by matched rule(s): "
                + ", ".join(sorted(matched_rules))
            )
        )
    if not lint_paths and not pytest_paths and not frontend:
        raise AffectedScopeError("affected-scope map expanded to zero checks")
    for selector in sorted({*lint_paths, *pytest_paths}):
        _assert_repository_selector(
            root,
            selector,
            context="expanded affected selector",
        )
    return AffectedSelection(
        inventory=inventory,
        map_digest=scope_map.digest,
        lint_paths=tuple(sorted(lint_paths)),
        pytest_paths=tuple(sorted(pytest_paths)),
        matched_rules=tuple(sorted(matched_rules)),
        path_rules=tuple(sorted(path_rules)),
        unknown_paths=tuple(sorted(unknown_paths)),
        fallback_complete_safe=fallback_complete_safe,
        fallback_reasons=tuple(sorted(set(fallback_reasons))),
        frontend=frontend,
        frontend_reason=frontend_reason,
    )


def _affected_planner_digest(scope_map: AffectedScopeMap) -> str:
    return sha256_digest(
        canonical_json_bytes(
            {
                "planner_id": DIAGNOSTIC_PLANNER_ID,
                "diagnostic_module_digest": _planner_digest(),
                "affected_module_digest": sha256_digest(
                    Path(__file__).read_bytes()
                ),
                "affected_map_digest": scope_map.digest,
            }
        )
    )


def run_affected_scope_diagnostic(
    *,
    repo_root: Path,
    output_root: Path,
    config: TestGateConfig,
    invocation_id: str,
    base_ref: str,
    map_path: Path = DEFAULT_AFFECTED_SCOPE_MAP_PATH,
    process_runner: Callable[..., ProcessResult] = run_command,
    source_collector: Callable[[Path], SourceIdentity] = collect_source_identity,
    inventory_collector: Callable[..., ChangedPathInventory] = (
        collect_changed_path_inventory
    ),
) -> DiagnosticRunResult:
    """Close changed paths, expand the map, then run one affected diagnostic."""

    root = repo_root.resolve(strict=True)
    source_before = source_collector(root)
    inventory = inventory_collector(root, base_ref=base_ref)
    scope_map = load_affected_scope_map(map_path, repo_root=root)
    selection = expand_affected_scope(
        root,
        inventory=inventory,
        scope_map=scope_map,
    )
    assert_source_stable(source_before, source_collector(root))
    return _run_diagnostic(
        repo_root=root,
        output_root=output_root,
        config=config,
        invocation_id=invocation_id,
        profile_id="affected_scope_diagnostic",
        stage_prefix="affected_scope",
        selection_document=selection.as_plan_dict(),
        lint_paths=selection.lint_paths,
        collection_selectors=selection.pytest_paths,
        planner_digest=_affected_planner_digest(scope_map),
        process_runner=process_runner,
        source_collector=source_collector,
        source_before=source_before,
    )
