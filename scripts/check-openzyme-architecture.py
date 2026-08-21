#!/usr/bin/env python3
"""Validate the source-bound OpenZyme component and ownership baseline.

This is an engineering-governance check. It reads source/configuration and an
in-memory rendering of the SQLite migration; it never imports runtime packages,
opens deployment state, or performs network/process/provider/HPC effects.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import tomllib
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_ROOT = ROOT / "docs" / "v3" / "architecture"
BASELINE_PATH = ARCHITECTURE_ROOT / "source-bound-baseline.json"
TABLE_OWNER_PATH = ARCHITECTURE_ROOT / "table-owner-manifest.json"
CAPABILITY_BASELINE_PATH = ARCHITECTURE_ROOT / "capability-workspace-baseline.json"
TRACEABILITY_PATH = ARCHITECTURE_ROOT / "source-document-traceability.json"
REEXPORT_LEDGER_PATH = ARCHITECTURE_ROOT / "temporary-reexport-ledger.json"
AUTHORITY_STORE_MAPPING_PATH = (
    ARCHITECTURE_ROOT / "authority-store-mapping.json"
)
COMPONENT_BOUNDARY_POLICY_PATH = (
    ARCHITECTURE_ROOT / "component-boundary-policy.json"
)
CATALOG_OWNER_PATH = ARCHITECTURE_ROOT / "catalog-owner-inventory.json"
DEPLOYMENT_STATE_INVENTORY_PATH = (
    ARCHITECTURE_ROOT / "pre-split-deployment-state-inventory.json"
)
QUALIFICATION_REGISTRY_PATH = (
    ROOT
    / "docs"
    / "v3"
    / "architecture-qualification"
    / "invariant-registry.json"
)
MIGRATION_PATH = (
    ROOT
    / "packages"
    / "openzyme-store-sqlite"
    / "src"
    / "openzyme_store_sqlite"
    / "migrations"
    / "001_file_workspace_final.sql"
)
_DEPENDENCY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*")


class ArchitectureCheckError(RuntimeError):
    pass


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _contract_canonical_digest(value: Any) -> str:
    """Match openzyme_contracts.canonical_sha256_digest for public identities."""

    payload = (
        json.dumps(
            value,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchitectureCheckError(
            f"cannot load {path.relative_to(ROOT)}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ArchitectureCheckError(
            f"{path.relative_to(ROOT)} must contain one object"
        )
    return value


def _source_ref(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _literal_keyword(call: ast.Call, name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            if isinstance(value, str) and value:
                return value
    return None


def _target_owner_for_tool(tool_name: str) -> str:
    if tool_name == "deep_research.start" or tool_name.endswith(
        ".index_research_file"
    ):
        return "openzyme.research"
    if tool_name.startswith(("scientific.", "attempt.")):
        return "openzyme.science"
    if tool_name.startswith("report"):
        return "openzyme.reporting"
    if tool_name.startswith("hpc."):
        return "openzyme.hpc"
    return "openzyme.kernel"


def _target_owner_for_route(method: str, route: str) -> str:
    del method
    if "/scientific-attempt" in route:
        return "openzyme.science"
    if "/workspace-revision-executions" in route:
        return "openzyme.compute"
    if route.startswith("/repositories/"):
        return "openzyme.workspace.git.lfs"
    return "openzyme.host.api"


def _target_owner_for_event(event_type: str) -> str:
    if event_type.startswith("scientific."):
        return "openzyme.science"
    if event_type.startswith("report"):
        return "openzyme.reporting"
    if event_type.startswith(("workspace.job", "workspace_revision")):
        return "openzyme.compute"
    if event_type.startswith("hpc."):
        return "openzyme.hpc"
    return "openzyme.kernel"


def _append_observed_item(
    items: dict[tuple[str, str, str], dict[str, Any]],
    *,
    kind: str,
    canonical_id: str,
    current_owner: str,
    target_owner: str,
    source_ref: str,
) -> None:
    key = (kind, canonical_id, current_owner)
    existing = items.get(key)
    if existing is None:
        items[key] = {
            "kind": kind,
            "canonical_id": canonical_id,
            "current_owner": current_owner,
            "target_owner": target_owner,
            "source_refs": [source_ref],
        }
        return
    if existing["target_owner"] != target_owner:
        raise ArchitectureCheckError(
            f"catalog identity {kind}:{canonical_id} has conflicting owners"
        )
    if source_ref not in existing["source_refs"]:
        existing["source_refs"].append(source_ref)
        existing["source_refs"].sort()


def observe_catalog_inventory() -> dict[str, Any]:
    """Observe current catalog identities without importing product packages."""

    inventory = _load_json(CATALOG_OWNER_PATH)
    if inventory.get("schema_id") != "openzyme_catalog_owner_inventory@1":
        raise ArchitectureCheckError("unexpected catalog owner inventory schema")
    items: dict[tuple[str, str, str], dict[str, Any]] = {}

    python_roots = (ROOT / "apps", ROOT / "packages")
    for python_root in python_roots:
        for source_path in sorted(python_root.glob("*/src/**/*.py")):
            source_ref = _source_ref(source_path)
            try:
                tree = ast.parse(
                    source_path.read_text(encoding="utf-8"), filename=source_ref
                )
            except (OSError, SyntaxError) as exc:
                raise ArchitectureCheckError(
                    f"cannot parse catalog source {source_ref}: {exc}"
                ) from exc
            distribution_path = source_path.relative_to(ROOT).parts[:2]
            pyproject = ROOT.joinpath(*distribution_path, "pyproject.toml")
            component_metadata = tomllib.loads(
                pyproject.read_text(encoding="utf-8")
            )["tool"]["openzyme"]["component"]
            current_owner = component_metadata["component_id"]
            component_kind = component_metadata["component_kind"]
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    tool_name = _literal_keyword(node, "tool_name")
                    if tool_name and "." in tool_name:
                        _append_observed_item(
                            items,
                            kind="tool",
                            canonical_id=tool_name,
                            current_owner=current_owner,
                            target_owner=(
                                current_owner
                                if component_kind in {"plugin", "product_plugin"}
                                else _target_owner_for_tool(tool_name)
                            ),
                            source_ref=source_ref,
                        )
                    event_type = _literal_keyword(node, "event_type")
                    if (
                        event_type is None
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                        and isinstance(node.func, (ast.Name, ast.Attribute))
                        and (
                            (isinstance(node.func, ast.Name) and node.func.id == "emit")
                            or (
                                isinstance(node.func, ast.Attribute)
                                and node.func.attr in {"emit", "_emit"}
                            )
                        )
                    ):
                        event_type = node.args[0].value
                    if event_type and "." in event_type:
                        _append_observed_item(
                            items,
                            kind="event",
                            canonical_id=event_type,
                            current_owner=current_owner,
                            target_owner=_target_owner_for_event(event_type),
                            source_ref=source_ref,
                        )
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if (
                        not isinstance(decorator, ast.Call)
                        or not isinstance(decorator.func, ast.Attribute)
                        or decorator.func.attr
                        not in {"get", "post", "put", "patch", "delete"}
                        or not decorator.args
                        or not isinstance(decorator.args[0], ast.Constant)
                        or not isinstance(decorator.args[0].value, str)
                    ):
                        continue
                    method = decorator.func.attr.upper()
                    route = decorator.args[0].value
                    _append_observed_item(
                        items,
                        kind="http_route",
                        canonical_id=f"{method} {route}",
                        current_owner=current_owner,
                        target_owner=_target_owner_for_route(method, route),
                        source_ref=source_ref,
                    )

    for manifest_path in sorted(ROOT.glob("packages/*/src/*/manifests/*.json")):
        manifest = _load_json(manifest_path)
        identity = manifest.get("identity", {})
        current_owner = str(identity.get("component_id", ""))
        if manifest.get("schema_version") != "openzyme_plugin_manifest@1":
            continue
        source_ref = _source_ref(manifest_path)
        target_owner = current_owner
        for tool in manifest.get("tools", []):
            contract = tool.get("contract", {})
            canonical_id = contract.get("tool_name")
            if (
                not isinstance(canonical_id, str)
                or not canonical_id
                or tool.get("owner_plugin_id") != current_owner
            ):
                raise ArchitectureCheckError(
                    f"manifest tool lacks exact owner/identity: {source_ref}"
                )
            _append_observed_item(
                items,
                kind="tool",
                canonical_id=canonical_id,
                current_owner=current_owner,
                target_owner=target_owner,
                source_ref=source_ref,
            )
        contribution_families = {
            "projections": "projection",
            "ui_renderers": "ui_renderer",
            "workers": "worker",
            "finish_validators": "finish_validator",
            "schemas": "schema",
            "migrations": "migration",
            "qualification_specs": "qualification_spec",
            "routes": "route",
            "http_routes": "manifest_http_route",
        }
        for field, kind in contribution_families.items():
            for contribution in manifest.get(field, []):
                canonical_id = contribution.get("contribution_id") or contribution.get(
                    "qualification_spec_id"
                ) or contribution.get("route_id")
                if not isinstance(canonical_id, str) or not canonical_id:
                    raise ArchitectureCheckError(
                        f"manifest contribution lacks identity: {source_ref}:{field}"
                    )
                _append_observed_item(
                    items,
                    kind=kind,
                    canonical_id=canonical_id,
                    current_owner=current_owner,
                    target_owner=target_owner,
                    source_ref=source_ref,
                )

    parser = configparser.ConfigParser()
    parser.read(ROOT / "pytest.ini", encoding="utf-8")
    marker_lines = parser.get("pytest", "markers", fallback="").splitlines()
    for line in marker_lines:
        marker = line.strip().split(":", maxsplit=1)[0].strip()
        if marker:
            _append_observed_item(
                items,
                kind="pytest_marker",
                canonical_id=marker,
                current_owner="openzyme.host.api",
                target_owner="openzyme.host.api",
                source_ref="pytest.ini",
            )

    registry = _load_json(QUALIFICATION_REGISTRY_PATH)
    for scenario in registry.get("scenarios", []):
        scenario_id = scenario.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise ArchitectureCheckError("qualification scenario lacks identity")
        _append_observed_item(
            items,
            kind="qualification_scenario",
            canonical_id=scenario_id,
            current_owner="openzyme.host.api",
            target_owner="openzyme.host.api",
            source_ref=_source_ref(QUALIFICATION_REGISTRY_PATH),
        )

    for composition_path in sorted(
        (ROOT / "distributions").glob("*/openzyme-composition.toml")
    ):
        composition = _load_composition(composition_path)
        source_ref = _source_ref(composition_path)
        distribution_id = str(composition["distribution"]["id"])
        for adapter in composition.get("adapters", []):
            component_id = str(adapter["component_id"])
            target_suffix = (
                f":{adapter['target_id']}" if adapter.get("target_id") else ""
            )
            _append_observed_item(
                items,
                kind="adapter_slot",
                canonical_id=(
                    f"{distribution_id}:{adapter['slot']}{target_suffix}"
                ),
                current_owner=component_id,
                target_owner=component_id,
                source_ref=source_ref,
            )
        for driver in composition.get("drivers", []):
            owning_plugin_id = str(driver["owning_plugin_id"])
            _append_observed_item(
                items,
                kind="driver",
                canonical_id=f"{distribution_id}:{driver['component_id']}",
                current_owner=owning_plugin_id,
                target_owner=owning_plugin_id,
                source_ref=source_ref,
            )

    for supplement in inventory.get("supplemental_surfaces", []):
        for source_ref in supplement["source_refs"]:
            _append_observed_item(
                items,
                kind=supplement["kind"],
                canonical_id=supplement["canonical_id"],
                current_owner=supplement["current_owner"],
                target_owner=supplement["target_owner"],
                source_ref=source_ref,
            )

    ordered = sorted(
        items.values(),
        key=lambda item: (
            item["kind"],
            item["canonical_id"],
            item["current_owner"],
        ),
    )
    counts: dict[str, int] = {}
    for item in ordered:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    authority_sets: dict[tuple[str, str], set[str]] = {}
    for item in ordered:
        authority_sets.setdefault(
            (item["kind"], item["canonical_id"]), set()
        ).add(item["current_owner"])
    duplicate_authorities = [
        {
            "kind": kind,
            "canonical_id": canonical_id,
            "current_owners": sorted(owners),
        }
        for (kind, canonical_id), owners in sorted(authority_sets.items())
        if len(owners) > 1
    ]
    return {
        "counts": dict(sorted(counts.items())),
        "catalog_digest": _canonical_digest(ordered),
        "duplicate_authorities": duplicate_authorities,
        "items": ordered,
    }


def validate_catalog_inventory(component_ids: set[str], *, enforce_digest: bool) -> dict[str, Any]:
    baseline = _load_json(CATALOG_OWNER_PATH)
    observation = observe_catalog_inventory()
    for item in observation["items"]:
        if item["current_owner"] not in component_ids:
            raise ArchitectureCheckError(
                f"catalog has unknown current owner: {item['current_owner']}"
            )
        if item["target_owner"] not in component_ids:
            raise ArchitectureCheckError(
                f"catalog has unknown target owner: {item['target_owner']}"
            )
        _validate_path_list(
            item["source_refs"],
            label=f"catalog.{item['kind']}.{item['canonical_id']}",
        )
    if enforce_digest and observation["counts"] != baseline.get("expected_counts"):
        raise ArchitectureCheckError("catalog inventory counts drifted")
    if enforce_digest and observation["catalog_digest"] != baseline.get(
        "catalog_digest"
    ):
        raise ArchitectureCheckError("catalog inventory digest drifted")
    if enforce_digest and observation["duplicate_authorities"] != baseline.get(
        "expected_temporary_duplicate_authorities"
    ):
        raise ArchitectureCheckError("catalog duplicate authority ledger drifted")
    return {
        "catalog_counts": observation["counts"],
        "catalog_digest": observation["catalog_digest"],
        "catalog_duplicate_authorities": observation["duplicate_authorities"],
    }


def validate_deployment_state_inventory_evidence(component_ids: set[str]) -> None:
    evidence = _load_json(DEPLOYMENT_STATE_INVENTORY_PATH)
    if evidence.get("schema_id") != "openzyme_pre_split_deployment_state_inventory@1":
        raise ArchitectureCheckError("unexpected deployment-state inventory schema")
    observation = evidence.get("observation", {})
    if observation.get("mode") != "sqlite_mode_ro_query_only":
        raise ArchitectureCheckError("deployment-state inventory is not read-only")
    if observation.get("mutation_applied") is not False:
        raise ArchitectureCheckError("deployment-state inventory records mutation")
    if observation.get("quick_check") != "ok":
        raise ArchitectureCheckError("deployment-state inventory failed quick_check")
    locator_id = observation.get("locator_id")
    if not isinstance(locator_id, str) or not locator_id or "/" in locator_id:
        raise ArchitectureCheckError("deployment-state inventory leaks a locator path")
    aggregates = evidence.get("classification_inputs", {}).get(
        "table_owner_aggregates", {}
    )
    if not aggregates or set(aggregates).difference(component_ids):
        raise ArchitectureCheckError(
            "deployment-state inventory has missing or unknown table owners"
        )
    if any(
        not isinstance(value, dict)
        or set(value) != {"tables", "rows"}
        or not all(isinstance(item, int) and item >= 0 for item in value.values())
        for value in aggregates.values()
    ):
        raise ArchitectureCheckError("deployment-state owner aggregates are invalid")
    if evidence.get("authority") != "read_only_engineering_evidence_only":
        raise ArchitectureCheckError("deployment-state evidence claims product authority")
    required_forbidden = {
        "not_at2_cutover_authority",
        "not_plugin_activation_authority",
        "not_live_provider_or_hpc_readiness",
        "not_session_task_or_scientific_terminal_authority",
    }
    if set(evidence.get("forbidden_inferences", [])) != required_forbidden:
        raise ArchitectureCheckError("deployment-state forbidden inferences drifted")


def _dependency_name(requirement: str) -> str:
    match = _DEPENDENCY_NAME.match(requirement)
    if match is None:
        raise ArchitectureCheckError(f"invalid dependency requirement: {requirement!r}")
    return match.group(0).lower().replace("_", "-")


def _python_component(path_text: str) -> dict[str, Any]:
    path = ROOT / path_text
    pyproject_path = path / "pyproject.toml"
    try:
        document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = document["project"]
        component = document["tool"]["openzyme"]["component"]
        wheel = document["tool"]["hatch"]["build"]["targets"]["wheel"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise ArchitectureCheckError(
            f"invalid component metadata: {pyproject_path}"
        ) from exc

    namespaces = tuple(sorted(Path(item).name for item in wheel.get("packages", ())))
    if not namespaces:
        raise ArchitectureCheckError(f"component has no wheel namespace: {path_text}")
    dependencies = tuple(sorted(project.get("dependencies", ())))
    entry_points = dict(sorted(project.get("scripts", {}).items()))
    for group, values in sorted(project.get("entry-points", {}).items()):
        for name, value in sorted(values.items()):
            entry_points[f"{group}:{name}"] = value
    return {
        "component_id": component["component_id"],
        "component_kind": component["component_kind"],
        "current_composition_owner": component["current_composition_owner"],
        "dependencies": list(dependencies),
        "description": project["description"],
        "distribution_name": project["name"],
        "entry_points": entry_points,
        "migration_state": component["migration_state"],
        "namespaces": list(namespaces),
        "path": path_text,
        "source_kind": "python_wheel",
    }


def _node_component() -> dict[str, Any]:
    path_text = "apps/openzyme-web-ui"
    path = ROOT / path_text / "package.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        component = document["openzymeComponent"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise ArchitectureCheckError(f"invalid component metadata: {path}") from exc
    return {
        "component_id": component["componentId"],
        "component_kind": component["componentKind"],
        "current_composition_owner": component["currentCompositionOwner"],
        "dependencies": [],
        "description": "OpenZyme browser delivery surface",
        "distribution_name": document["name"],
        "entry_points": dict(sorted(document.get("scripts", {}).items())),
        "migration_state": component["migrationState"],
        "namespaces": [],
        "path": path_text,
        "source_kind": "node_workspace",
    }


def observe_component_inventory() -> dict[str, Any]:
    root_document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    members = tuple(root_document["tool"]["uv"]["workspace"]["members"])
    if len(set(members)) != len(members):
        raise ArchitectureCheckError(
            "root uv workspace contains duplicate member paths"
        )
    if any(Path(member).parts[0] not in {"apps", "packages"} for member in members):
        raise ArchitectureCheckError(
            "Python workspace roots are restricted to apps/ and packages/"
        )
    components = [_python_component(member) for member in members]
    components.append(_node_component())
    components.sort(key=lambda item: item["component_id"])

    component_ids = [item["component_id"] for item in components]
    distribution_names = [item["distribution_name"] for item in components]
    namespaces = [namespace for item in components for namespace in item["namespaces"]]
    for label, values in (
        ("component ID", component_ids),
        ("distribution name", distribution_names),
        ("Python namespace", namespaces),
    ):
        if len(set(values)) != len(values):
            raise ArchitectureCheckError(f"duplicate {label} in component inventory")
    known_ids = set(component_ids)
    for item in components:
        owner = item["current_composition_owner"]
        if owner not in {"self", "uncomposed"} and owner not in known_ids:
            raise ArchitectureCheckError(
                f"unknown composition owner {owner!r} for {item['component_id']}"
            )
    return {
        "python_workspace_roots": ["apps", "packages"],
        "configuration_roots": ["distributions"],
        "components": components,
    }


def observe_import_graph(inventory: dict[str, Any]) -> dict[str, Any]:
    namespace_owner = {
        namespace: item["distribution_name"]
        for item in inventory["components"]
        for namespace in item["namespaces"]
    }
    path_owner = {
        item["path"]: item["distribution_name"]
        for item in inventory["components"]
        if item["source_kind"] == "python_wheel"
    }
    edges: set[tuple[str, str]] = set()
    for path_text, source in path_owner.items():
        for source_path in sorted((ROOT / path_text / "src").rglob("*.py")):
            try:
                tree = ast.parse(
                    source_path.read_text(encoding="utf-8"),
                    filename=str(source_path.relative_to(ROOT)),
                )
            except (OSError, SyntaxError) as exc:
                raise ArchitectureCheckError(
                    f"cannot parse {source_path}: {exc}"
                ) from exc
            imported_roots: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_roots.update(
                        alias.name.split(".", maxsplit=1)[0] for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots.add(node.module.split(".", maxsplit=1)[0])
            for namespace in imported_roots:
                target = namespace_owner.get(namespace)
                if target is not None and target != source:
                    edges.add((source, target))
    return {
        "edges": [
            {"source": source, "target": target} for source, target in sorted(edges)
        ]
    }


def _load_composition(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ArchitectureCheckError(f"invalid Distribution manifest: {path}") from exc


def _validate_distribution_scaffolds(
    component_ids: set[str],
    *,
    component_kinds: dict[str, str] | None = None,
) -> None:
    paths = {
        "openzyme.standard": ROOT
        / "distributions"
        / "openzyme-standard"
        / "openzyme-composition.toml",
        "enzymedesign": ROOT
        / "distributions"
        / "enzymedesign"
        / "openzyme-composition.toml",
    }
    for expected_id, path in paths.items():
        document = _load_composition(path)
        if document.get("schema_id") != "openzyme_composition@1":
            raise ArchitectureCheckError(f"unexpected composition schema: {path}")
        manifest_state = document.get("manifest_state")
        if manifest_state not in {"scaffold_not_activatable", "active"}:
            raise ArchitectureCheckError(
                f"Distribution has an unknown manifest state: {path}"
            )
        if manifest_state == "active":
            digest_values = tuple(_named_digest_values(document))
            invalid_digests = sorted(
                name
                for name, value in digest_values
                if not isinstance(value, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
                or value == "sha256:" + "0" * 64
            )
            if not digest_values or invalid_digests:
                raise ArchitectureCheckError(
                    "active Distribution lacks exact non-placeholder digests: "
                    f"{path}; invalid={invalid_digests}"
                )
        if document.get("distribution", {}).get("id") != expected_id:
            raise ArchitectureCheckError(f"Distribution identity mismatch: {path}")
        if document.get("policy") != {
            "ambient_discovery_enables_components": False,
            "session_hot_swap": False,
        }:
            raise ArchitectureCheckError(
                f"Distribution policy is not fail-closed: {path}"
            )
        adapters = document.get("adapters", [])
        adapter_slots = [
            (item["slot"], item.get("target_id")) for item in adapters
        ]
        if len(set(adapter_slots)) != len(adapter_slots):
            raise ArchitectureCheckError(f"duplicate Adapter slot: {path}")
        required_plugins = {
            item["component_id"] for item in document["plugins"]["required"]
        }
        optional_plugins = {
            item["component_id"] for item in document["plugins"]["optional"]
        }
        delivery_surfaces = {
            item["component_id"] for item in document["delivery_surfaces"]
        }
        driver_ids = {
            item["component_id"] for item in document.get("drivers", [])
        }
        selected_ids = {
            document["kernel"]["component_id"],
            *(item["component_id"] for item in adapters),
            *required_plugins,
            *optional_plugins,
            *delivery_surfaces,
        }
        missing = sorted(selected_ids.difference(component_ids))
        if missing:
            raise ArchitectureCheckError(
                f"Distribution references unknown components {missing}: {path}"
            )
        if required_plugins.intersection(optional_plugins):
            raise ArchitectureCheckError(
                f"Plugin cannot be required and optional: {path}"
            )
        selected_plugins = required_plugins | optional_plugins
        if component_kinds is not None:
            if component_kinds[document["kernel"]["component_id"]] != "kernel":
                raise ArchitectureCheckError(
                    f"Distribution selected a non-Kernel component: {path}"
                )
            for adapter in adapters:
                if component_kinds[adapter["component_id"]] != "adapter":
                    raise ArchitectureCheckError(
                        f"Distribution Adapter slot has wrong component kind: {path}"
                    )
            for plugin_id in selected_plugins:
                if component_kinds[plugin_id] not in {"plugin", "product_plugin"}:
                    raise ArchitectureCheckError(
                        f"Distribution Plugin selection has wrong component kind: {path}"
                    )
            for surface_id in delivery_surfaces:
                if component_kinds[surface_id] not in {
                    "client",
                    "delivery_adapter",
                }:
                    raise ArchitectureCheckError(
                        f"Distribution delivery surface has wrong component kind: {path}"
                    )
        for driver in document.get("drivers", []):
            if driver["owning_plugin_id"] not in selected_plugins:
                raise ArchitectureCheckError(f"Driver owner is not selected: {path}")
        driver_slots = [item["slot"] for item in document.get("drivers", [])]
        if len(set(driver_slots)) != len(driver_slots):
            raise ArchitectureCheckError(f"duplicate Driver slot: {path}")
        if len(driver_ids) != len(document.get("drivers", [])):
            raise ArchitectureCheckError(f"duplicate Driver ID: {path}")
    standard = _load_composition(paths["openzyme.standard"])
    if standard["plugins"]["required"]:
        raise ArchitectureCheckError(
            "OpenZyme Standard required semantic Plugin set must remain empty"
        )


def _named_digest_values(
    value: object,
    *,
    prefix: str = "",
) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if str(key).endswith("_digest"):
                found.append((name, item))
            found.extend(_named_digest_values(item, prefix=name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_named_digest_values(item, prefix=f"{prefix}[{index}]"))
    return found


def _component_source_paths(component: dict[str, Any]) -> tuple[Path, ...]:
    if component["source_kind"] != "python_wheel":
        return ()
    source_root = ROOT / component["path"] / "src"
    return tuple(
        path
        for path in sorted(source_root.rglob("*.py"))
        if "__pycache__" not in path.parts
    )


def _source_import_roots(source_path: Path) -> set[str]:
    try:
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"),
            filename=str(source_path.relative_to(ROOT)),
        )
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        raise ArchitectureCheckError(
            f"cannot parse component source {source_path.relative_to(ROOT)}"
        ) from exc
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", maxsplit=1)[0])
    return roots


def validate_forbidden_source_text(
    component_id: str,
    source_text: str,
    policy: dict[str, Any],
) -> None:
    tree = ast.parse(source_text)
    declaration_lines: set[int] = set()
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(
            isinstance(target, ast.Name) and "FORBIDDEN" in target.id.upper()
            for target in targets
        ):
            declaration_lines.update(
                range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1)
            )
    lowered = "\n".join(
        line
        for line_number, line in enumerate(source_text.lower().splitlines(), start=1)
        if line_number not in declaration_lines
    )
    matches = sorted(
        token
        for token in policy.get("forbidden_source_vocabulary", {}).get(
            component_id, []
        )
        if token.lower() in lowered
    )
    if matches:
        raise ArchitectureCheckError(
            f"forbidden source vocabulary for {component_id}: {matches}"
        )


def validate_component_source_policy(
    component_id: str,
    component_kind: str,
    source_text: str,
    policy: dict[str, Any],
    *,
    source_label: str,
) -> None:
    try:
        tree = ast.parse(source_text, filename=source_label)
    except SyntaxError as exc:
        raise ArchitectureCheckError(
            f"cannot parse component source {source_label}"
        ) from exc
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", maxsplit=1)[0])
    forbidden_roots = {
        *policy.get("forbidden_import_roots", {}).get(component_id, []),
        *policy.get("forbidden_import_roots_by_kind", {}).get(
            component_kind, []
        ),
    }
    matches = sorted(roots.intersection(forbidden_roots))
    if matches:
        raise ArchitectureCheckError(
            f"forbidden implementation import for {component_id}: "
            f"{matches} in {source_label}"
        )
    validate_forbidden_source_text(component_id, source_text, policy)
    if component_kind == "adapter" and any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == "ToolContribution"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "ToolContribution"
        )
        for node in ast.walk(tree)
    ):
        raise ArchitectureCheckError(
            f"Adapter declares an Agent tool: {component_id}"
        )
    if component_kind == "distribution" and roots.intersection(
        {"openzyme_domain", "sqlite3"}
    ):
        raise ArchitectureCheckError(
            f"Distribution imports canonical-state implementation: {component_id}"
        )


def validate_component_boundaries(
    inventory: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
) -> None:
    policy = policy or _load_json(COMPONENT_BOUNDARY_POLICY_PATH)
    if policy.get("schema_id") != "openzyme_component_boundary_policy@1":
        raise ArchitectureCheckError("unexpected component boundary policy schema")
    if policy.get("policy") != {
        "adapter_may_declare_agent_tool": False,
        "ambient_activation": False,
        "distribution_may_own_canonical_state": False,
        "driver_may_activate_without_owner": False,
        "standard_is_semantic_dependency": False,
    }:
        raise ArchitectureCheckError("component boundary policy weakened")

    components = inventory["components"]
    by_id = {component["component_id"]: component for component in components}
    by_distribution = {
        component["distribution_name"]: component for component in components
    }
    enforced_states = set(policy.get("enforced_migration_states", []))
    legacy_states = set(policy.get("legacy_exempt_states", []))
    if enforced_states.intersection(legacy_states):
        raise ArchitectureCheckError("component policy states overlap")
    allowed_kinds = policy.get("allowed_dependency_kinds", {})
    exceptions = policy.get("allowed_component_dependency_exceptions", {})

    for component in components:
        state = component["migration_state"]
        if state not in enforced_states | legacy_states:
            raise ArchitectureCheckError(
                f"component has unclassified migration state: {component['component_id']}"
            )
        if state in legacy_states:
            continue
        kind = component["component_kind"]
        if kind not in allowed_kinds:
            raise ArchitectureCheckError(
                f"component kind has no dependency policy: {kind}"
            )
        permitted_kinds = set(allowed_kinds[kind])
        permitted_ids = set(exceptions.get(component["component_id"], []))
        dependency_names = {
            _dependency_name(requirement)
            for requirement in component["dependencies"]
        }
        for dependency_name in dependency_names:
            target = by_distribution.get(dependency_name)
            if target is None:
                continue
            if target["component_id"] in permitted_ids:
                continue
            if target["component_kind"] not in permitted_kinds:
                raise ArchitectureCheckError(
                    f"forbidden component dependency: {component['component_id']} "
                    f"-> {target['component_id']}"
                )
        forbidden_external = {
            name.lower().replace("_", "-")
            for name in policy.get("forbidden_external_dependencies", {}).get(
                component["component_id"], []
            )
        }
        external_matches = sorted(dependency_names.intersection(forbidden_external))
        if external_matches:
            raise ArchitectureCheckError(
                f"forbidden external dependency for {component['component_id']}: "
                f"{external_matches}"
            )

        source_paths = _component_source_paths(component)
        for source_path in source_paths:
            source_text = source_path.read_text(encoding="utf-8")
            validate_component_source_policy(
                component["component_id"],
                kind,
                source_text,
                policy,
                source_label=str(source_path.relative_to(ROOT)),
            )

        if component["source_kind"] == "python_wheel":
            constant_values: dict[str, str] = {}
            for source_path in source_paths:
                tree = ast.parse(
                    source_path.read_text(encoding="utf-8"),
                    filename=str(source_path.relative_to(ROOT)),
                )
                for node in tree.body:
                    if (
                        isinstance(node, ast.Assign)
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                        and node.targets[0].id in {"COMPONENT_ID", "COMPONENT_KIND"}
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                    ):
                        constant_values[node.targets[0].id] = node.value.value
            if constant_values and constant_values != {
                "COMPONENT_ID": component["component_id"],
                "COMPONENT_KIND": kind,
            }:
                raise ArchitectureCheckError(
                    f"component source constants drifted: {component['component_id']}"
                )

    distribution_ids = {
        component["component_id"]
        for component in components
        if component["component_kind"] == "distribution"
    }
    for component in components:
        if component["component_kind"] == "distribution":
            continue
        dependency_ids = {
            by_distribution[name]["component_id"]
            for name in (
                _dependency_name(requirement)
                for requirement in component["dependencies"]
            )
            if name in by_distribution
        }
        if dependency_ids.intersection(distribution_ids):
            raise ArchitectureCheckError(
                f"Distribution used as semantic dependency: {component['component_id']}"
            )

    component_ids = set(by_id)
    _validate_distribution_scaffolds(
        component_ids,
        component_kinds={
            component_id: component["component_kind"]
            for component_id, component in by_id.items()
        },
    )


def validate_historical_path_exclusion(inventory: dict[str, Any]) -> None:
    policy = _load_json(COMPONENT_BOUNDARY_POLICY_PATH)
    historical_roots = tuple(policy.get("historical_roots", []))
    for component in inventory["components"]:
        path = component["path"]
        if any(path == root or path.startswith(f"{root}/") for root in historical_roots):
            raise ArchitectureCheckError(
                f"historical component entered active inventory: {path}"
            )
        if any(
            any(
                entry_point.startswith(f"{root}.")
                or f"/{root}/" in entry_point
                for root in ("archive", "legacy", "old")
            )
            for entry_point in component["entry_points"].values()
        ):
            raise ArchitectureCheckError(
                f"historical entry point entered active component: {path}"
            )
        for source_path in _component_source_paths(component):
            roots = _source_import_roots(source_path)
            if roots.intersection({"archive", "legacy", "old"}):
                raise ArchitectureCheckError(
                    f"active source imports historical namespace: "
                    f"{source_path.relative_to(ROOT)}"
                )
    pytest_text = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    if "testpaths = apps packages" not in pytest_text:
        raise ArchitectureCheckError(
            "active pytest roots are no longer restricted to apps/packages"
        )
    for excluded in ("legacy", "old", "openspec"):
        if not re.search(rf"(?m)^\s+{re.escape(excluded)}\s*$", pytest_text):
            raise ArchitectureCheckError(
                f"historical pytest exclusion is missing: {excluded}"
            )


def _database_schema() -> tuple[sqlite3.Connection, dict[str, list[str]]]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    except (OSError, sqlite3.Error) as exc:
        connection.close()
        raise ArchitectureCheckError(
            "cannot render the current SQLite migration"
        ) from exc
    objects = {
        kind: [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = ? AND name NOT LIKE 'sqlite_%' ORDER BY name",
                (kind,),
            )
        ]
        for kind in ("table", "index", "trigger")
    }
    return connection, objects


def _matches_owner_rule(table_name: str, rule: dict[str, Any]) -> bool:
    return table_name in rule.get("exact_names", []) or any(
        table_name.startswith(prefix) for prefix in rule.get("prefixes", [])
    )


def validate_table_owners(
    component_ids: set[str],
    *,
    enforce_digest: bool = True,
) -> dict[str, Any]:
    manifest = _load_json(TABLE_OWNER_PATH)
    if manifest.get("schema_id") != "openzyme_table_owner_manifest@1":
        raise ArchitectureCheckError("unexpected table owner manifest schema")
    if manifest.get("physical_table_rename_policy") != "retain_names_in_this_change":
        raise ArchitectureCheckError(
            "table owner manifest must retain physical table names"
        )
    connection, objects = _database_schema()
    rules = manifest.get("semantic_owner_rules", [])
    rule_ids = [rule["rule_id"] for rule in rules]
    if len(set(rule_ids)) != len(rule_ids):
        raise ArchitectureCheckError("duplicate table owner rule ID")
    owners: dict[str, str] = {}
    for table_name in objects["table"]:
        matches = [rule for rule in rules if _matches_owner_rule(table_name, rule)]
        if len(matches) != 1:
            raise ArchitectureCheckError(
                f"table {table_name!r} has {len(matches)} semantic owners"
            )
        owner = matches[0]["target_owner"]
        if owner not in component_ids:
            raise ArchitectureCheckError(f"unknown table owner {owner!r}")
        owners[table_name] = owner

    origin_owners: dict[tuple[str, str], str] = {}
    for kind in ("index", "trigger"):
        for name in objects[kind]:
            row = connection.execute(
                "SELECT tbl_name FROM sqlite_master WHERE type = ? AND name = ?",
                (kind, name),
            ).fetchone()
            if row is None or row[0] not in owners:
                raise ArchitectureCheckError(f"{kind} {name!r} has no owned table")
            origin_owners[(kind, name)] = owners[str(row[0])]
    foreign_keys = []
    for table_name in objects["table"]:
        for row in connection.execute(f'PRAGMA foreign_key_list("{table_name}")'):
            referenced_table = row[2]
            if referenced_table not in owners:
                raise ArchitectureCheckError(
                    f"foreign key from {table_name!r} references unowned {referenced_table!r}"
                )
            foreign_keys.append((table_name, referenced_table, row[3], row[4]))
    connection.close()

    counts = {
        "tables": len(objects["table"]),
        "indexes": len(objects["index"]),
        "triggers": len(objects["trigger"]),
        "foreign_keys": len(foreign_keys),
    }
    if counts != manifest.get("expected_object_counts"):
        raise ArchitectureCheckError(
            f"SQLite object counts drifted: expected {manifest.get('expected_object_counts')}, "
            f"observed {counts}"
        )
    owner_projection = [
        {"table": table_name, "target_owner": owners[table_name]}
        for table_name in sorted(owners)
    ]
    if enforce_digest and _canonical_digest(owner_projection) != manifest.get(
        "table_owner_digest"
    ):
        raise ArchitectureCheckError("table owner projection digest drifted")
    _validate_owner_migration_catalog(
        manifest=manifest,
        owners=owners,
        objects=objects,
        origin_owners=origin_owners,
    )
    return {"counts": counts, "table_owner_digest": _canonical_digest(owner_projection)}


def _validate_owner_migration_catalog(
    *,
    manifest: dict[str, Any],
    owners: dict[str, str],
    objects: dict[str, set[str]],
    origin_owners: dict[tuple[str, str], str],
) -> None:
    catalog_ref = manifest.get("owner_migration_catalog")
    if not isinstance(catalog_ref, str):
        raise ArchitectureCheckError("table owner manifest lacks migration catalog")
    catalog_path = ROOT / catalog_ref
    catalog = _load_json(catalog_path)
    if catalog.get("schema_id") != "openzyme_owner_partitioned_migration_catalog@1":
        raise ArchitectureCheckError("unexpected owner migration catalog schema")
    payload = {key: value for key, value in catalog.items() if key != "catalog_digest"}
    if _contract_canonical_digest(payload) != catalog.get("catalog_digest"):
        raise ArchitectureCheckError("owner migration catalog digest drifted")
    if catalog.get("source_migration") != manifest.get("source_migration"):
        raise ArchitectureCheckError("owner migration source identity drifted")
    if catalog.get("table_owner_manifest_digest") != manifest.get(
        "table_owner_digest"
    ):
        raise ArchitectureCheckError("owner migration table-owner digest drifted")
    if catalog.get("expected_object_counts") != manifest.get(
        "expected_object_counts"
    ):
        raise ArchitectureCheckError("owner migration object counts drifted")
    source_path = ROOT / catalog["source_migration"]
    if _file_digest(source_path) != catalog.get("source_migration_digest"):
        raise ArchitectureCheckError("owner migration source bytes drifted")
    bundles = catalog.get("bundles", [])
    order = catalog.get("bundle_order", [])
    if order != [bundle.get("migration_id") for bundle in bundles] or len(
        order
    ) != len(set(order)):
        raise ArchitectureCheckError("owner migration bundle order is not closed")
    phase_rank = {"tables": 10, "indexes": 20, "triggers": 30, "finalize": 40}
    observed_ranks: list[int] = []
    observed_objects: set[str] = set()
    expected_objects = set().union(
        objects["table"],
        objects["index"],
        objects["trigger"],
        {"seed:deployment_schema_state", "pragma:user_version"},
    )
    for bundle in bundles:
        phase = bundle.get("phase")
        if phase not in phase_rank:
            raise ArchitectureCheckError("owner migration phase is unknown")
        observed_ranks.append(phase_rank[phase])
        owner = bundle.get("semantic_owner")
        if owner not in set(owners.values()):
            raise ArchitectureCheckError("owner migration names an unknown owner")
        resource_ref = bundle.get("resource")
        if not isinstance(resource_ref, str):
            raise ArchitectureCheckError("owner migration resource is absent")
        resource = (
            ROOT
            / "packages"
            / "openzyme-store-sqlite"
            / "src"
            / "openzyme_store_sqlite"
            / resource_ref
        )
        if not resource.is_file() or _file_digest(resource) != bundle.get(
            "resource_digest"
        ):
            raise ArchitectureCheckError(
                f"owner migration resource drifted: {resource_ref}"
            )
        identities = bundle.get("object_identities", [])
        if (
            not isinstance(identities, list)
            or len(identities) != bundle.get("object_count")
            or len(identities) != len(set(identities))
            or observed_objects.intersection(identities)
        ):
            raise ArchitectureCheckError("owner migration object identity is not unique")
        for identity in identities:
            if phase == "tables" and owners.get(identity) != owner:
                raise ArchitectureCheckError(
                    f"table migration crossed owner boundary: {identity}"
                )
            if phase in {"indexes", "triggers"}:
                object_kind = "index" if phase == "indexes" else "trigger"
                if origin_owners.get((object_kind, identity)) != owner:
                    raise ArchitectureCheckError(
                        f"{object_kind} migration crossed owner boundary: {identity}"
                    )
            if phase == "finalize" and owner != "openzyme.store.sqlite":
                raise ArchitectureCheckError("finalize statement is not Store-owned")
        observed_objects.update(identities)
    if observed_ranks != sorted(observed_ranks):
        raise ArchitectureCheckError("owner migration phases are not topologically ordered")
    if observed_objects != expected_objects:
        raise ArchitectureCheckError(
            "owner migration object closure drifted: "
            f"missing={sorted(expected_objects - observed_objects)}; "
            f"unexpected={sorted(observed_objects - expected_objects)}"
        )


def _validate_path_list(values: list[str], *, label: str) -> None:
    if len(set(values)) != len(values):
        raise ArchitectureCheckError(f"duplicate paths in {label}")
    for value in values:
        path = ROOT / value
        if not path.exists():
            raise ArchitectureCheckError(f"stale path in {label}: {value}")


def validate_capability_and_workspace_baseline(component_ids: set[str]) -> None:
    baseline = _load_json(CAPABILITY_BASELINE_PATH)
    if baseline.get("schema_id") != "openzyme_capability_workspace_baseline@1":
        raise ArchitectureCheckError("unexpected capability/workspace baseline schema")
    facts = baseline.get("capability_fact_classes", [])
    if [item["fact_class"] for item in facts] != [
        "extension",
        "resource",
        "authority",
        "tool_affordance",
    ]:
        raise ArchitectureCheckError(
            "capability baseline must keep four ordered fact classes"
        )
    records = [*facts, *baseline.get("workspace_runtime_flows", [])]
    record_ids = [item.get("fact_class", item.get("flow_id")) for item in records]
    if len(set(record_ids)) != len(record_ids):
        raise ArchitectureCheckError("duplicate capability/workspace baseline identity")
    for item in records:
        if item["target_owner"] not in component_ids:
            raise ArchitectureCheckError(
                f"unknown baseline target owner: {item['target_owner']}"
            )
        _validate_path_list(
            item["source_refs"], label=str(item.get("flow_id", item.get("fact_class")))
        )


def validate_authority_store_mapping(component_ids: set[str]) -> None:
    manifest = _load_json(AUTHORITY_STORE_MAPPING_PATH)
    if manifest.get("schema_id") != "openzyme_authority_store_mapping_manifest@1":
        raise ArchitectureCheckError("unexpected authority store mapping schema")
    public = manifest.get("public_contract", {})
    if public != {
        "owner": "openzyme.contracts",
        "schema_version": "agent_authority_lease@1",
        "symbol": "AgentAuthorityLease",
        "legacy_public_alias_in_at2": False,
    }:
        raise ArchitectureCheckError("authority public contract mapping drifted")
    storage = manifest.get("physical_storage", {})
    if storage != {
        "store_adapter": "openzyme.store.sqlite",
        "semantic_owner": "openzyme.kernel",
        "table_name": "agent_capability_lease_records",
        "legacy_schema_version": "agent_capability_lease@1",
        "rename_policy": "retain_physical_name_in_this_change",
        "writer_cutover_state": "legacy_writer_active",
    }:
        raise ArchitectureCheckError("authority physical mapping drifted")
    if {public["owner"], storage["store_adapter"], storage["semantic_owner"]} - component_ids:
        raise ArchitectureCheckError("authority mapping names an unknown component")
    identity = manifest.get("identity_mapping", {})
    if identity.get("generation") != "workspace_generation":
        raise ArchitectureCheckError("authority generation mapping drifted")
    if identity.get("fence") != "state_version":
        raise ArchitectureCheckError("authority fence mapping drifted")
    if identity.get("expires_at", "missing") is not None:
        raise ArchitectureCheckError("legacy authority mapping invented an expiry")
    if manifest.get("state_mapping") != {
        "pending_workspace": "pending",
        "active": "active",
        "revoked": "revoked",
    }:
        raise ArchitectureCheckError("authority state mapping drifted")
    operation_mapping = manifest.get("operation_mapping", {})
    expected_capabilities = {
        "filesystem_read",
        "filesystem_write",
        "shell_process",
        "git",
        "git_lfs",
        "ordinary_network",
        "upload",
        "download",
        "ssh",
        "rsync_scp",
        "hpc_login_workspace_crud",
        "slurm_operations",
    }
    if set(operation_mapping) != expected_capabilities or any(
        not operations or len(set(operations)) != len(operations)
        for operations in operation_mapping.values()
    ):
        raise ArchitectureCheckError("authority operation mapping is not closed")
    profiles = manifest.get("profile_templates", {})
    if set(profiles) != {"general", "executor"}:
        raise ArchitectureCheckError("authority issuance templates drifted")
    if set(profiles["general"]) != expected_capabilities - {
        "ssh",
        "rsync_scp",
        "hpc_login_workspace_crud",
        "slurm_operations",
    } or profiles["executor"] != [
        *profiles["general"],
        "ssh",
        "rsync_scp",
        "hpc_login_workspace_crud",
        "slurm_operations",
    ]:
        raise ArchitectureCheckError("authority profile templates no longer map exactly")
    rules = _load_json(TABLE_OWNER_PATH).get("semantic_owner_rules", [])
    matches = [
        rule
        for rule in rules
        if _matches_owner_rule(storage["table_name"], rule)
    ]
    if len(matches) != 1 or matches[0]["target_owner"] != storage["semantic_owner"]:
        raise ArchitectureCheckError("authority table semantic owner drifted")
    connection, objects = _database_schema()
    connection.close()
    if storage["table_name"] not in objects["table"]:
        raise ArchitectureCheckError("authority physical table is absent")
    _validate_path_list(manifest.get("source_refs", []), label="authority mapping source")
    _validate_path_list(manifest.get("test_refs", []), label="authority mapping test")


def validate_traceability(component_ids: set[str]) -> None:
    registry = _load_json(TRACEABILITY_PATH)
    if registry.get("schema_id") != "openzyme_source_document_traceability@2":
        raise ArchitectureCheckError("unexpected source-document traceability schema")
    required_dimensions = (
        "commands_paths_configuration",
        "compatibility",
        "error_semantics",
        "forbidden_fallback",
        "identity",
        "lifecycle",
        "owner",
        "persistence",
    )
    if tuple(registry.get("required_contract_dimensions", [])) != required_dimensions:
        raise ArchitectureCheckError(
            "source-document required contract dimensions drifted"
        )
    content_bound_seam_ids = registry.get("content_bound_seam_ids", [])
    if (
        content_bound_seam_ids != sorted(set(content_bound_seam_ids))
        or not content_bound_seam_ids
    ):
        raise ArchitectureCheckError(
            "source-document content-bound seam ids are not closed"
        )
    entries = registry.get("entries", [])
    seam_ids = [entry["seam_id"] for entry in entries]
    if len(set(seam_ids)) != len(seam_ids):
        raise ArchitectureCheckError("duplicate traceability seam")
    if not entries:
        raise ArchitectureCheckError("traceability registry is empty")
    indexed = {entry["seam_id"]: entry for entry in entries}
    if not set(content_bound_seam_ids) <= set(indexed):
        raise ArchitectureCheckError(
            "source-document content-bound seam is missing"
        )

    def bundle_digest(paths: list[str], *, label: str) -> str:
        _validate_path_list(paths, label=label)
        return _canonical_digest(
            [
                {"content_digest": _file_digest(ROOT / path), "path": path}
                for path in sorted(paths)
            ]
        )

    for entry in entries:
        if entry["owner"] not in component_ids:
            raise ArchitectureCheckError(
                f"unknown traceability owner: {entry['owner']}"
            )
        for key in ("source_refs", "document_refs", "test_refs"):
            values = entry.get(key, [])
            if not values:
                raise ArchitectureCheckError(f"{entry['seam_id']} has no {key}")
            _validate_path_list(values, label=f"{entry['seam_id']}.{key}")
        if entry["seam_id"] not in content_bound_seam_ids:
            continue
        dimensions = entry.get("contract_dimensions", [])
        if tuple(dimensions) != required_dimensions:
            raise ArchitectureCheckError(
                f"{entry['seam_id']} contract dimensions drifted"
            )
        for field_name, refs_name in (
            ("source_bundle_digest", "source_refs"),
            ("document_bundle_digest", "document_refs"),
            ("test_bundle_digest", "test_refs"),
        ):
            expected = bundle_digest(
                entry[refs_name],
                label=f"{entry['seam_id']}.{refs_name}",
            )
            if entry.get(field_name) != expected:
                raise ArchitectureCheckError(
                    f"{entry['seam_id']} {field_name} drifted"
                )


def validate_reexport_ledger() -> None:
    ledger = _load_json(REEXPORT_LEDGER_PATH)
    if ledger.get("schema_id") != "openzyme_temporary_reexport_ledger@1":
        raise ArchitectureCheckError("unexpected re-export ledger schema")
    if ledger.get("external_consumer_policy") != "no_out_of_repository_consumers":
        raise ArchitectureCheckError(
            "re-export ledger contradicts the consumer decision"
        )
    entries = ledger.get("entries", [])
    if ledger.get("retirement_status") == "retired_in_18_1":
        if entries != []:
            raise ArchitectureCheckError(
                "retired temporary re-export ledger entries must be empty"
            )
        retired_projects = (
            "packages/openzyme-core/pyproject.toml",
            "packages/openzyme-domain/pyproject.toml",
            "packages/openzyme-execution/pyproject.toml",
            "packages/openzyme-runtime/pyproject.toml",
        )
        present = [relative for relative in retired_projects if (ROOT / relative).exists()]
        if present:
            raise ArchitectureCheckError(
                f"retired authority package metadata remains: {present!r}"
            )
        forbidden_roots = {
            "openzyme_core",
            "openzyme_domain",
            "openzyme_execution",
            "openzyme_runtime",
        }
        violations: list[str] = []
        for source_root in (*ROOT.glob("apps/*/src"), *ROOT.glob("packages/*/src")):
            for source_path in source_root.rglob("*.py"):
                tree = ast.parse(
                    source_path.read_text(encoding="utf-8"),
                    filename=str(source_path.relative_to(ROOT)),
                )
                imported_roots: set[str] = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        imported_roots.add(node.module.split(".", 1)[0])
                    elif isinstance(node, ast.Import):
                        imported_roots.update(
                            alias.name.split(".", 1)[0] for alias in node.names
                        )
                if imported_roots.intersection(forbidden_roots):
                    violations.append(source_path.relative_to(ROOT).as_posix())
        if violations:
            raise ArchitectureCheckError(
                f"current source imports retired authority namespace: {violations!r}"
            )
        return
    raise ArchitectureCheckError("temporary re-export ledger is not retired")

    identities = [(item["legacy_namespace"], item["symbol"]) for item in entries]
    if len(set(identities)) != len(identities):
        raise ArchitectureCheckError("duplicate temporary re-export identity")
    required_fields = {
        "legacy_namespace",
        "legacy_module",
        "canonical_namespace",
        "canonical_module",
        "symbol",
        "authority_rule",
        "introduced_phase",
        "deletion_phase",
        "caller_refs",
        "shim_source_ref",
        "compatibility_test_refs",
    }
    canonical_modules = {
        "openzyme_contracts.reliability": ROOT
        / "packages"
        / "openzyme-contracts"
        / "src"
        / "openzyme_contracts"
        / "reliability.py",
        "openzyme_contracts.failures": ROOT
        / "packages"
        / "openzyme-contracts"
        / "src"
        / "openzyme_contracts"
        / "failures.py",
        "openzyme_contracts.diagnostics": ROOT
        / "packages"
        / "openzyme-contracts"
        / "src"
        / "openzyme_contracts"
        / "diagnostics.py",
        "openzyme_contracts.repository_bindings": ROOT
        / "packages"
        / "openzyme-contracts"
        / "src"
        / "openzyme_contracts"
        / "repository_bindings.py",
        "openzyme_contracts.control_plane": ROOT
        / "packages"
        / "openzyme-contracts"
        / "src"
        / "openzyme_contracts"
        / "control_plane.py",
        "openzyme_contracts.workspace_checkpoints": ROOT
        / "packages"
        / "openzyme-contracts"
        / "src"
        / "openzyme_contracts"
        / "workspace_checkpoints.py",
        "openzyme_contracts.workspace_publications": ROOT
        / "packages"
        / "openzyme-contracts"
        / "src"
        / "openzyme_contracts"
        / "workspace_publications.py",
        "openzyme_contracts.revision_paths": ROOT
        / "packages"
        / "openzyme-contracts"
        / "src"
        / "openzyme_contracts"
        / "revision_paths.py",
        "openzyme_execution_contracts.workspace_job_wire": ROOT
        / "packages"
        / "openzyme-execution-contracts"
        / "src"
        / "openzyme_execution_contracts"
        / "workspace_job_wire.py",
        "openzyme_compute.workspace_revision_executions": ROOT
        / "packages"
        / "openzyme-compute"
        / "src"
        / "openzyme_compute"
        / "workspace_revision_executions.py",
        "openzyme_science.attempts": ROOT
        / "packages"
        / "openzyme-science"
        / "src"
        / "openzyme_science"
        / "attempts.py",
        "openzyme_science.deliverables": ROOT
        / "packages"
        / "openzyme-science"
        / "src"
        / "openzyme_science"
        / "deliverables.py",
        "openzyme_science.refs": ROOT
        / "packages"
        / "openzyme-science"
        / "src"
        / "openzyme_science"
        / "refs.py",
        "openzyme_reporting.contracts": ROOT
        / "packages"
        / "openzyme-reporting"
        / "src"
        / "openzyme_reporting"
        / "contracts.py",
        "openzyme_reporting.refs": ROOT
        / "packages"
        / "openzyme-reporting"
        / "src"
        / "openzyme_reporting"
        / "refs.py",
        "openzyme_research.contracts": ROOT
        / "packages"
        / "openzyme-research"
        / "src"
        / "openzyme_research"
        / "contracts.py",
        "openzyme_compute.contracts": ROOT
        / "packages"
        / "openzyme-compute"
        / "src"
        / "openzyme_compute"
        / "contracts.py",
        "openzyme_process_podman.state": ROOT
        / "packages"
        / "openzyme-process-podman"
        / "src"
        / "openzyme_process_podman"
        / "state.py",
        "openzyme_process_podman.lifecycle": ROOT
        / "packages"
        / "openzyme-process-podman"
        / "src"
        / "openzyme_process_podman"
        / "lifecycle.py",
        "openzyme_hpc.contracts": ROOT
        / "packages"
        / "openzyme-hpc"
        / "src"
        / "openzyme_hpc"
        / "contracts.py",
        "openzyme_workspace_git_lfs.agent_workspaces": ROOT
        / "packages"
        / "openzyme-workspace-git-lfs"
        / "src"
        / "openzyme_workspace_git_lfs"
        / "agent_workspaces.py",
        "openzyme_workspace_git_lfs.lfs": ROOT
        / "packages"
        / "openzyme-workspace-git-lfs"
        / "src"
        / "openzyme_workspace_git_lfs"
        / "lfs.py",
    }

    def literal_exports(path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                value = ast.literal_eval(node.value)
                if not isinstance(value, list) or any(
                    not isinstance(item, str) for item in value
                ):
                    break
                return set(value)
        raise ArchitectureCheckError(f"{path.relative_to(ROOT)} has no literal __all__")

    expected_symbols = {
        (module, symbol)
        for module, path in canonical_modules.items()
        for symbol in literal_exports(path)
    }
    observed_symbols = {
        (item.get("canonical_module"), item.get("symbol")) for item in entries
    }
    if not observed_symbols.issubset(expected_symbols):
        raise ArchitectureCheckError(
            "temporary re-export ledger names symbols absent from canonical exports: "
            f"unexpected={sorted(observed_symbols - expected_symbols)}"
        )

    direct_callers: dict[str, set[str]] = {
        symbol: set() for _, symbol in expected_symbols
    }
    registered_shim_paths = {item["shim_source_ref"] for item in entries}
    registered_legacy_modules = {
        item["legacy_namespace"] for item in entries
    } | {item["legacy_module"] for item in entries}
    source_paths = sorted(
        [
            *(ROOT / "apps").rglob("*.py"),
            *(ROOT / "packages").rglob("*.py"),
        ]
    )
    for source_path in source_paths:
        if "__pycache__" in source_path.parts:
            continue
        if source_path.relative_to(ROOT).as_posix() in registered_shim_paths:
            continue
        try:
            tree = ast.parse(
                source_path.read_text(encoding="utf-8"),
                filename=str(source_path.relative_to(ROOT)),
            )
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            raise ArchitectureCheckError(
                f"cannot inspect legacy caller {source_path.relative_to(ROOT)}"
            ) from exc
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.ImportFrom)
                or node.module not in registered_legacy_modules
            ):
                continue
            for alias in node.names:
                if alias.name in direct_callers:
                    direct_callers[alias.name].add(
                        source_path.relative_to(ROOT).as_posix()
                    )

    for item in entries:
        if set(item) != required_fields:
            raise ArchitectureCheckError(
                f"temporary re-export entry fields are not closed: {item.get('symbol')}"
            )
        if item["legacy_namespace"] != item["legacy_module"].split(".", 1)[0]:
            raise ArchitectureCheckError("temporary re-export has wrong legacy namespace")
        if item["canonical_namespace"] != item["canonical_module"].split(".", 1)[0]:
            raise ArchitectureCheckError(
                "temporary re-export has wrong canonical namespace"
            )
        if item["authority_rule"] != "canonical_implementation_only":
            raise ArchitectureCheckError(
                "temporary re-export permits a second implementation"
            )
        if item["introduced_phase"] not in {
            "3_contract_extraction",
            "7_runtime_adapter_split",
        }:
            raise ArchitectureCheckError("temporary re-export phase drifted")
        if item["deletion_phase"] != "16_offline_cutover":
            raise ArchitectureCheckError("temporary re-export deletion is unbounded")
        if set(item["caller_refs"]) != direct_callers[item["symbol"]]:
            raise ArchitectureCheckError(
                f"temporary re-export caller ledger drifted: {item['symbol']}"
            )
        _validate_path_list(item["caller_refs"], label=f"re-export {item['symbol']}")
        _validate_path_list(
            [item["shim_source_ref"]],
            label=f"re-export shim {item['symbol']}",
        )
        _validate_path_list(
            item["compatibility_test_refs"],
            label=f"re-export test {item['symbol']}",
        )

    shim_paths = sorted({item["shim_source_ref"] for item in entries})
    for shim_path_text in shim_paths:
        shim_path = ROOT / shim_path_text
        tree = ast.parse(
            shim_path.read_text(encoding="utf-8"),
            filename=shim_path_text,
        )
        registered_symbols = {
            item["symbol"]
            for item in entries
            if item["shim_source_ref"] == shim_path_text
        }
        imported_symbols: set[str] = set()
        canonical_module_names = {
            item["canonical_module"]
            for item in entries
            if item["shim_source_ref"] == shim_path_text
        }
        literal_all: set[str] | None = None
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                raise ArchitectureCheckError(
                    "temporary re-export shim contains a second implementation: "
                    f"{shim_path_text}"
                )
            if isinstance(node, ast.AnnAssign):
                raise ArchitectureCheckError(
                    "temporary re-export shim contains a second implementation: "
                    f"{shim_path_text}"
                )
            if isinstance(node, ast.Assign):
                if not (
                    len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "__all__"
                ):
                    raise ArchitectureCheckError(
                        "temporary re-export shim contains a second implementation: "
                        f"{shim_path_text}"
                    )
                try:
                    exported = ast.literal_eval(node.value)
                except (ValueError, TypeError) as exc:
                    raise ArchitectureCheckError(
                        f"temporary re-export shim has non-literal __all__: {shim_path_text}"
                    ) from exc
                if not isinstance(exported, list) or any(
                    not isinstance(symbol, str) for symbol in exported
                ):
                    raise ArchitectureCheckError(
                        f"temporary re-export shim has invalid __all__: {shim_path_text}"
                    )
                literal_all = set(exported)
            if isinstance(node, ast.ImportFrom) and node.module in canonical_module_names:
                for alias in node.names:
                    if alias.name == "*":
                        imported_symbols.update(
                            literal_exports(canonical_modules[node.module])
                        )
                    elif alias.name != "__all__":
                        imported_symbols.add(alias.name)
        if imported_symbols != registered_symbols or (
            literal_all is not None and literal_all != registered_symbols
        ):
            raise ArchitectureCheckError(
                "temporary re-export ledger does not match registered legacy exports: "
                f"{shim_path_text}"
            )

    for foundation_root in (
        ROOT / "packages" / "openzyme-contracts" / "src",
        ROOT / "packages" / "openzyme-execution-contracts" / "src",
        ROOT / "packages" / "openzyme-extension-spi" / "src",
        ROOT / "packages" / "openzyme-kernel" / "src",
        ROOT / "packages" / "openzyme-compute" / "src",
        ROOT / "packages" / "openzyme-hpc" / "src",
        ROOT / "packages" / "openzyme-workspace-git-lfs" / "src",
        ROOT / "packages" / "openzyme-process-podman" / "src",
        ROOT / "packages" / "openzyme-reporting" / "src",
        ROOT / "packages" / "openzyme-research" / "src",
        ROOT / "packages" / "openzyme-science" / "src",
    ):
        for source_path in foundation_root.rglob("*.py"):
            tree = ast.parse(
                source_path.read_text(encoding="utf-8"),
                filename=str(source_path.relative_to(ROOT)),
            )
            for node in ast.walk(tree):
                imported = None
                if isinstance(node, ast.ImportFrom):
                    imported = node.module
                elif isinstance(node, ast.Import):
                    imported = ",".join(alias.name for alias in node.names)
                if imported and "openzyme_domain" in imported:
                    raise ArchitectureCheckError(
                        "foundation package imports legacy openzyme_domain: "
                        f"{source_path.relative_to(ROOT)}"
                    )


def validate_source_baseline() -> dict[str, Any]:
    baseline = _load_json(BASELINE_PATH)
    if baseline.get("schema_id") != "openzyme_source_bound_architecture_baseline@1":
        raise ArchitectureCheckError("unexpected source-bound baseline schema")
    if baseline.get("decisions") != {
        "external_consumers": "none_confirmed",
        "revision_contract": "git_shaped_retained_for_this_change",
        "repository_split": "deferred_to_separate_change",
    }:
        raise ArchitectureCheckError("source-bound decisions drifted")

    inventory = observe_component_inventory()
    import_graph = observe_import_graph(inventory)
    if _canonical_digest(inventory) != baseline.get("component_inventory_digest"):
        raise ArchitectureCheckError("component inventory digest drifted")
    if _canonical_digest(import_graph) != baseline.get("import_graph_digest"):
        raise ArchitectureCheckError("Python import graph digest drifted")

    observed_edges = {
        (item["source"], item["target"]) for item in import_graph["edges"]
    }
    declared_reverse_edges = {
        (item["source"], item["target"])
        for item in baseline.get("legacy_reverse_edges", [])
    }
    if not declared_reverse_edges.issubset(observed_edges):
        raise ArchitectureCheckError(
            "declared legacy reverse dependency is no longer source-bound"
        )

    component_ids = {item["component_id"] for item in inventory["components"]}
    expected_ids = set(baseline.get("expected_component_ids", []))
    if component_ids != expected_ids:
        raise ArchitectureCheckError(
            f"component ID closure drifted: missing={sorted(expected_ids - component_ids)}, "
            f"unexpected={sorted(component_ids - expected_ids)}"
        )

    by_distribution = {
        item["distribution_name"]: item for item in inventory["components"]
    }
    dependency_limits = {
        "openzyme-contracts": set(),
        "openzyme-extension-spi": {"openzyme-contracts"},
        "openzyme-kernel": {
            "openzyme-contracts",
            "openzyme-extension-spi",
            "openzyme-runtime-spi",
        },
    }
    for distribution_name, allowed in dependency_limits.items():
        actual = {
            _dependency_name(item)
            for item in by_distribution[distribution_name]["dependencies"]
        }
        if actual != allowed:
            raise ArchitectureCheckError(
                f"runtime dependency closure drifted for {distribution_name}: {sorted(actual)}"
            )

    validate_component_boundaries(inventory)
    table_result = validate_table_owners(component_ids)
    validate_capability_and_workspace_baseline(component_ids)
    catalog_result = validate_catalog_inventory(component_ids, enforce_digest=True)
    validate_deployment_state_inventory_evidence(component_ids)
    validate_authority_store_mapping(component_ids)
    validate_traceability(component_ids)
    validate_reexport_ledger()
    validate_historical_path_exclusion(inventory)
    return {
        "component_count": len(inventory["components"]),
        "component_inventory_digest": _canonical_digest(inventory),
        "import_edge_count": len(import_graph["edges"]),
        "import_graph_digest": _canonical_digest(import_graph),
        **table_result,
        **catalog_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--observe",
        action="store_true",
        help="print current inventory/import/table digests without accepting them",
    )
    arguments = parser.parse_args()
    try:
        if arguments.observe:
            inventory = observe_component_inventory()
            import_graph = observe_import_graph(inventory)
            component_ids = {item["component_id"] for item in inventory["components"]}
            table_result = validate_table_owners(component_ids, enforce_digest=False)
            catalog_result = validate_catalog_inventory(
                component_ids, enforce_digest=False
            )
            result = {
                "component_count": len(inventory["components"]),
                "component_inventory_digest": _canonical_digest(inventory),
                "component_ids": sorted(component_ids),
                "import_edge_count": len(import_graph["edges"]),
                "import_graph_digest": _canonical_digest(import_graph),
                "import_edges": import_graph["edges"],
                **table_result,
                **catalog_result,
            }
        else:
            result = validate_source_baseline()
    except ArchitectureCheckError as exc:
        print(f"architecture-check: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
