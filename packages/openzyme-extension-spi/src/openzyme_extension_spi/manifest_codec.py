from __future__ import annotations

from collections.abc import Mapping
import importlib.metadata
import json
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from openzyme_contracts import TOOL_SPEC_SCHEMA_VERSION
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_json_bytes

from .contributions import CapabilityCardinality
from .contributions import CapabilityProvision
from .contributions import CapabilityRequirement
from .contributions import CapabilityRequirementKind
from .contributions import HttpMethod
from .contributions import HttpRouteContribution
from .contributions import NamedContribution
from .contributions import QualificationSpec
from .contributions import RouteContribution
from .contributions import ToolContribution
from .discovery import ExtensionManifestLocator
from .manifests import ADAPTER_MANIFEST_SCHEMA_VERSION
from .manifests import DRIVER_MANIFEST_SCHEMA_VERSION
from .manifests import PLUGIN_MANIFEST_SCHEMA_VERSION
from .manifests import AdapterManifest
from .manifests import ComponentIdentity
from .manifests import ComponentKind
from .manifests import ComponentManifest
from .manifests import DriverManifest
from .manifests import PluginManifest


MAX_COMPONENT_MANIFEST_BYTES = 4 * 1024 * 1024


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"component manifest contains duplicate key {key!r}")
        result[key] = value
    return result


def _object(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _array(value: Any, *, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    return tuple(value)


def _text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _boolean(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be boolean")
    return value


def _closed(
    value: Mapping[str, Any],
    *,
    field_name: str,
    fields: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    observed = set(value)
    required = fields.difference(optional)
    if not required.issubset(observed) or not observed.issubset(fields):
        raise ValueError(
            f"{field_name} fields are closed; "
            f"missing={sorted(required - observed)}, "
            f"unknown={sorted(observed - fields)}"
        )


def _strings(value: Any, *, field_name: str) -> tuple[str, ...]:
    return tuple(
        _text(item, field_name=f"{field_name}[]")
        for item in _array(value, field_name=field_name)
    )


def _identity(value: Any) -> ComponentIdentity:
    data = _object(value, field_name="identity")
    _closed(
        data,
        field_name="identity",
        fields=frozenset(
            {
                "component_id",
                "component_kind",
                "component_version",
                "distribution_name",
                "distribution_version",
                "build_digest",
                "contract_digest",
            }
        ),
    )
    return ComponentIdentity(
        component_id=_text(data["component_id"], field_name="component_id"),
        component_kind=ComponentKind(data["component_kind"]),
        component_version=_text(
            data["component_version"],
            field_name="component_version",
        ),
        distribution_name=_text(
            data["distribution_name"],
            field_name="distribution_name",
        ),
        distribution_version=_text(
            data["distribution_version"],
            field_name="distribution_version",
        ),
        build_digest=_text(data["build_digest"], field_name="build_digest"),
        contract_digest=_text(
            data["contract_digest"],
            field_name="contract_digest",
        ),
    )


def _named(value: Any, *, field_name: str) -> NamedContribution:
    data = _object(value, field_name=field_name)
    _closed(
        data,
        field_name=field_name,
        fields=frozenset({"contribution_id", "contract_digest"}),
    )
    return NamedContribution(
        contribution_id=_text(
            data["contribution_id"],
            field_name=f"{field_name}.contribution_id",
        ),
        contract_digest=_text(
            data["contract_digest"],
            field_name=f"{field_name}.contract_digest",
        ),
    )


def _provision(value: Any, *, field_name: str) -> CapabilityProvision:
    data = _object(value, field_name=field_name)
    _closed(
        data,
        field_name=field_name,
        fields=frozenset(
            {"capability_id", "contract_version", "operations", "cardinality"}
        ),
    )
    return CapabilityProvision(
        capability_id=_text(
            data["capability_id"],
            field_name=f"{field_name}.capability_id",
        ),
        contract_version=_text(
            data["contract_version"],
            field_name=f"{field_name}.contract_version",
        ),
        operations=_strings(
            data["operations"],
            field_name=f"{field_name}.operations",
        ),
        cardinality=CapabilityCardinality(data["cardinality"]),
    )


def _requirement(value: Any, *, field_name: str) -> CapabilityRequirement:
    data = _object(value, field_name=field_name)
    _closed(
        data,
        field_name=field_name,
        fields=frozenset(
            {
                "capability_id",
                "contract_spec",
                "kind",
                "operations",
                "version_spec",
                "same_target_as",
            }
        ),
    )
    version_spec = data["version_spec"]
    same_target_as = data["same_target_as"]
    return CapabilityRequirement(
        capability_id=_text(
            data["capability_id"],
            field_name=f"{field_name}.capability_id",
        ),
        contract_spec=_text(
            data["contract_spec"],
            field_name=f"{field_name}.contract_spec",
        ),
        kind=CapabilityRequirementKind(data["kind"]),
        operations=_strings(
            data["operations"],
            field_name=f"{field_name}.operations",
        ),
        version_spec=(
            None
            if version_spec is None
            else _text(version_spec, field_name=f"{field_name}.version_spec")
        ),
        same_target_as=(
            None
            if same_target_as is None
            else _text(
                same_target_as,
                field_name=f"{field_name}.same_target_as",
            )
        ),
    )


def _tool_spec(value: Any, *, field_name: str) -> ToolSpec:
    data = _object(value, field_name=field_name)
    _closed(
        data,
        field_name=field_name,
        fields=frozenset(
            {
                "schema_version",
                "tool_name",
                "description",
                "input_schema",
                "output_schema",
                "required_authorities",
                "approval_policy_id",
            }
        ),
    )
    if data["schema_version"] != TOOL_SPEC_SCHEMA_VERSION:
        raise ValueError(f"{field_name} has unsupported schema_version")
    approval = data["approval_policy_id"]
    return ToolSpec(
        tool_name=_text(data["tool_name"], field_name=f"{field_name}.tool_name"),
        description=_text(
            data["description"],
            field_name=f"{field_name}.description",
        ),
        input_schema=_object(
            data["input_schema"],
            field_name=f"{field_name}.input_schema",
        ),
        output_schema=_object(
            data["output_schema"],
            field_name=f"{field_name}.output_schema",
        ),
        required_authorities=_strings(
            data["required_authorities"],
            field_name=f"{field_name}.required_authorities",
        ),
        approval_policy_id=(
            None
            if approval is None
            else _text(approval, field_name=f"{field_name}.approval_policy_id")
        ),
    )


def _tool(value: Any, *, field_name: str) -> ToolContribution:
    data = _object(value, field_name=field_name)
    _closed(
        data,
        field_name=field_name,
        fields=frozenset(
            {
                "owner_plugin_id",
                "runtime_id",
                "contract",
                "requirements",
                "requires_workspace",
                "requires_explicit_route",
            }
        ),
    )
    return ToolContribution(
        owner_plugin_id=_text(
            data["owner_plugin_id"],
            field_name=f"{field_name}.owner_plugin_id",
        ),
        runtime_id=_text(
            data["runtime_id"],
            field_name=f"{field_name}.runtime_id",
        ),
        contract=_tool_spec(
            data["contract"],
            field_name=f"{field_name}.contract",
        ),
        requirements=tuple(
            _requirement(item, field_name=f"{field_name}.requirements[{index}]")
            for index, item in enumerate(
                _array(
                    data["requirements"],
                    field_name=f"{field_name}.requirements",
                )
            )
        ),
        requires_workspace=_boolean(
            data["requires_workspace"],
            field_name=f"{field_name}.requires_workspace",
        ),
        requires_explicit_route=_boolean(
            data["requires_explicit_route"],
            field_name=f"{field_name}.requires_explicit_route",
        ),
    )


def _qualification(value: Any, *, field_name: str) -> QualificationSpec:
    data = _object(value, field_name=field_name)
    _closed(
        data,
        field_name=field_name,
        fields=frozenset(
            {
                "qualification_spec_id",
                "owner_plugin_id",
                "capability_id",
                "contract_version",
                "version_argv",
                "smoke_argv",
                "expected_result_schema",
                "required_resource_capabilities",
            }
        ),
    )
    return QualificationSpec(
        qualification_spec_id=_text(
            data["qualification_spec_id"],
            field_name=f"{field_name}.qualification_spec_id",
        ),
        owner_plugin_id=_text(
            data["owner_plugin_id"],
            field_name=f"{field_name}.owner_plugin_id",
        ),
        capability_id=_text(
            data["capability_id"],
            field_name=f"{field_name}.capability_id",
        ),
        contract_version=_text(
            data["contract_version"],
            field_name=f"{field_name}.contract_version",
        ),
        version_argv=_strings(
            data["version_argv"],
            field_name=f"{field_name}.version_argv",
        ),
        smoke_argv=_strings(
            data["smoke_argv"],
            field_name=f"{field_name}.smoke_argv",
        ),
        expected_result_schema=_object(
            data["expected_result_schema"],
            field_name=f"{field_name}.expected_result_schema",
        ),
        required_resource_capabilities=_strings(
            data["required_resource_capabilities"],
            field_name=f"{field_name}.required_resource_capabilities",
        ),
    )


def _route(value: Any, *, field_name: str) -> RouteContribution:
    data = _object(value, field_name=field_name)
    _closed(
        data,
        field_name=field_name,
        fields=frozenset(
            {
                "route_id",
                "owner_component_id",
                "capability_ids",
                "route_kind",
                "route_contract_digest",
                "target_id",
                "driver_id",
                "requirements",
            }
        ),
        optional=frozenset({"requirements"}),
    )
    target = data["target_id"]
    driver = data["driver_id"]
    return RouteContribution(
        route_id=_text(data["route_id"], field_name=f"{field_name}.route_id"),
        owner_component_id=_text(
            data["owner_component_id"],
            field_name=f"{field_name}.owner_component_id",
        ),
        capability_ids=_strings(
            data["capability_ids"],
            field_name=f"{field_name}.capability_ids",
        ),
        route_kind=_text(
            data["route_kind"],
            field_name=f"{field_name}.route_kind",
        ),
        route_contract_digest=_text(
            data["route_contract_digest"],
            field_name=f"{field_name}.route_contract_digest",
        ),
        target_id=(
            None
            if target is None
            else _text(target, field_name=f"{field_name}.target_id")
        ),
        driver_id=(
            None
            if driver is None
            else _text(driver, field_name=f"{field_name}.driver_id")
        ),
        requirements=tuple(
            _requirement(item, field_name=f"{field_name}.requirements[]")
            for item in data.get("requirements", ())
        ),
    )


def _http_route(value: Any, *, field_name: str) -> HttpRouteContribution:
    data = _object(value, field_name=field_name)
    _closed(
        data,
        field_name=field_name,
        fields=frozenset(
            {
                "route_id",
                "owner_plugin_id",
                "method",
                "path",
                "contract_digest",
            }
        ),
    )
    return HttpRouteContribution(
        route_id=_text(data["route_id"], field_name=f"{field_name}.route_id"),
        owner_plugin_id=_text(
            data["owner_plugin_id"],
            field_name=f"{field_name}.owner_plugin_id",
        ),
        method=HttpMethod(data["method"]),
        path=_text(data["path"], field_name=f"{field_name}.path"),
        contract_digest=_text(
            data["contract_digest"],
            field_name=f"{field_name}.contract_digest",
        ),
    )


def _records(
    value: Any,
    *,
    field_name: str,
    parser: Any,
) -> tuple[Any, ...]:
    return tuple(
        parser(item, field_name=f"{field_name}[{index}]")
        for index, item in enumerate(_array(value, field_name=field_name))
    )


def _adapter(data: Mapping[str, Any]) -> AdapterManifest:
    _closed(
        data,
        field_name="adapter manifest",
        fields=frozenset(
            {
                "schema_version",
                "identity",
                "required_contracts",
                "port_contracts",
                "configuration_schema_digest",
                "preflight_contract_digest",
                "target_scoped",
            }
        ),
    )
    return AdapterManifest(
        identity=_identity(data["identity"]),
        required_contracts=_strings(
            data["required_contracts"],
            field_name="required_contracts",
        ),
        port_contracts=_records(
            data["port_contracts"],
            field_name="port_contracts",
            parser=_named,
        ),
        configuration_schema_digest=_text(
            data["configuration_schema_digest"],
            field_name="configuration_schema_digest",
        ),
        preflight_contract_digest=_text(
            data["preflight_contract_digest"],
            field_name="preflight_contract_digest",
        ),
        target_scoped=_boolean(
            data["target_scoped"],
            field_name="target_scoped",
        ),
    )


def _plugin(data: Mapping[str, Any]) -> PluginManifest:
    _closed(
        data,
        field_name="plugin manifest",
        fields=frozenset(
            {
                "schema_version",
                "identity",
                "required_kernel_contract",
                "required_extension_spi_contract",
                "provides",
                "requires",
                "tools",
                "qualification_specs",
                "routes",
                "http_routes",
                "projections",
                "ui_renderers",
                "workers",
                "finish_validators",
                "schemas",
                "migrations",
                "transaction_participants",
                "state_namespace",
                "migration_bundle_digest",
                "configuration_schema_digest",
            }
        ),
    )
    state_namespace = data["state_namespace"]
    migration_digest = data["migration_bundle_digest"]
    configuration_digest = data["configuration_schema_digest"]
    return PluginManifest(
        identity=_identity(data["identity"]),
        required_kernel_contract=_text(
            data["required_kernel_contract"],
            field_name="required_kernel_contract",
        ),
        required_extension_spi_contract=_text(
            data["required_extension_spi_contract"],
            field_name="required_extension_spi_contract",
        ),
        provides=_records(data["provides"], field_name="provides", parser=_provision),
        requires=_records(
            data["requires"],
            field_name="requires",
            parser=_requirement,
        ),
        tools=_records(data["tools"], field_name="tools", parser=_tool),
        qualification_specs=_records(
            data["qualification_specs"],
            field_name="qualification_specs",
            parser=_qualification,
        ),
        routes=_records(data["routes"], field_name="routes", parser=_route),
        http_routes=_records(
            data["http_routes"],
            field_name="http_routes",
            parser=_http_route,
        ),
        projections=_records(
            data["projections"],
            field_name="projections",
            parser=_named,
        ),
        ui_renderers=_records(
            data["ui_renderers"],
            field_name="ui_renderers",
            parser=_named,
        ),
        workers=_records(data["workers"], field_name="workers", parser=_named),
        finish_validators=_records(
            data["finish_validators"],
            field_name="finish_validators",
            parser=_named,
        ),
        schemas=_records(data["schemas"], field_name="schemas", parser=_named),
        migrations=_records(
            data["migrations"],
            field_name="migrations",
            parser=_named,
        ),
        transaction_participants=_records(
            data["transaction_participants"],
            field_name="transaction_participants",
            parser=_named,
        ),
        state_namespace=(
            None
            if state_namespace is None
            else _text(state_namespace, field_name="state_namespace")
        ),
        migration_bundle_digest=(
            None
            if migration_digest is None
            else _text(migration_digest, field_name="migration_bundle_digest")
        ),
        configuration_schema_digest=(
            None
            if configuration_digest is None
            else _text(
                configuration_digest,
                field_name="configuration_schema_digest",
            )
        ),
    )


def _driver(data: Mapping[str, Any]) -> DriverManifest:
    _closed(
        data,
        field_name="driver manifest",
        fields=frozenset(
            {
                "schema_version",
                "identity",
                "owning_plugin_id",
                "owning_plugin_contract",
                "route_kind",
                "required_port_contracts",
                "workload_contract_digest",
                "result_contract_digest",
            }
        ),
    )
    return DriverManifest(
        identity=_identity(data["identity"]),
        owning_plugin_id=_text(
            data["owning_plugin_id"],
            field_name="owning_plugin_id",
        ),
        owning_plugin_contract=_text(
            data["owning_plugin_contract"],
            field_name="owning_plugin_contract",
        ),
        route_kind=_text(data["route_kind"], field_name="route_kind"),
        required_port_contracts=_strings(
            data["required_port_contracts"],
            field_name="required_port_contracts",
        ),
        workload_contract_digest=_text(
            data["workload_contract_digest"],
            field_name="workload_contract_digest",
        ),
        result_contract_digest=_text(
            data["result_contract_digest"],
            field_name="result_contract_digest",
        ),
    )


def parse_component_manifest_json(source: str | bytes) -> ComponentManifest:
    """Parse one closed manifest and derive its canonical representation."""

    if isinstance(source, bytes):
        if len(source) > MAX_COMPONENT_MANIFEST_BYTES:
            raise ValueError("component manifest exceeds the byte budget")
        source = source.decode("utf-8")
    elif not isinstance(source, str):
        raise TypeError("component manifest must be UTF-8 text or bytes")
    if len(source.encode("utf-8")) > MAX_COMPONENT_MANIFEST_BYTES:
        raise ValueError("component manifest exceeds the byte budget")
    parsed = json.loads(source, object_pairs_hook=_unique_object)
    data = _object(parsed, field_name="component manifest")
    schema_version = data.get("schema_version")
    if schema_version == ADAPTER_MANIFEST_SCHEMA_VERSION:
        manifest: ComponentManifest = _adapter(data)
    elif schema_version == PLUGIN_MANIFEST_SCHEMA_VERSION:
        manifest = _plugin(data)
    elif schema_version == DRIVER_MANIFEST_SCHEMA_VERSION:
        manifest = _driver(data)
    else:
        raise ValueError("component manifest schema_version is unsupported")
    if manifest.to_dict() != json.loads(canonical_json_bytes(manifest.to_dict())):
        raise AssertionError("component manifest canonicalization is not stable")
    return manifest


def verify_located_component_manifest(
    locator: ExtensionManifestLocator,
    source: str | bytes,
    *,
    installed_distribution_name: str,
    installed_distribution_version: str,
) -> ComponentManifest:
    """Verify locator, installed package and canonical manifest as one identity."""

    if installed_distribution_name != locator.distribution_name:
        raise ValueError("located manifest distribution name drifted")
    if installed_distribution_version != locator.distribution_version:
        raise ValueError("located manifest distribution version drifted")
    manifest = parse_component_manifest_json(source)
    identity = manifest.identity
    mismatches = {
        "component_id": identity.component_id != locator.component_id,
        "component_kind": identity.component_kind is not locator.component_kind,
        "distribution_name": identity.distribution_name != locator.distribution_name,
        "distribution_version": (
            identity.distribution_version != locator.distribution_version
        ),
        "manifest_digest": manifest.manifest_digest != locator.manifest_digest,
    }
    drifted = sorted(field for field, mismatch in mismatches.items() if mismatch)
    if drifted:
        raise ValueError(f"located component manifest identity drifted: {drifted}")
    return manifest


def read_located_component_manifest(
    locator: ExtensionManifestLocator,
) -> ComponentManifest:
    """Read a selected package resource without importing its runtime module."""

    distribution = importlib.metadata.distribution(locator.distribution_name)
    installed_name = distribution.metadata.get("Name")
    if not isinstance(installed_name, str):
        raise ValueError("installed distribution has no exact Name metadata")
    resource = PurePosixPath(
        *locator.resource_package.split("."),
        *PurePosixPath(locator.resource_name).parts,
    ).as_posix()
    installed_files = {
        str(item).replace("\\", "/"): item for item in distribution.files or ()
    }
    located_file = installed_files.get(resource)
    if located_file is not None:
        source = distribution.locate_file(located_file).read_bytes()
    else:
        source = _read_editable_manifest_resource(
            distribution,
            resource=resource,
        )
    return verify_located_component_manifest(
        locator,
        source,
        installed_distribution_name=installed_name,
        installed_distribution_version=distribution.version,
    )


def _read_editable_manifest_resource(
    distribution: importlib.metadata.Distribution,
    *,
    resource: str,
) -> bytes:
    """Resolve a plain-path editable install without executing a .pth file."""

    roots: list[Path] = []
    for installed_file in distribution.files or ():
        installed_name = str(installed_file).replace("\\", "/")
        if not installed_name.endswith(".pth"):
            continue
        pth_path = Path(distribution.locate_file(installed_file))
        for line in pth_path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            if value.startswith("import ") or "\x00" in value:
                raise ValueError(
                    "editable manifest discovery refuses executable .pth content"
                )
            candidate_root = Path(value)
            if not candidate_root.is_absolute():
                candidate_root = pth_path.parent / candidate_root
            roots.append(candidate_root.resolve(strict=True))
    matches: list[Path] = []
    for root in roots:
        candidate = (root / resource).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("editable manifest resource escaped its source root") from exc
        if candidate.is_file():
            matches.append(candidate)
    if len(matches) != 1:
        raise ValueError(
            "located manifest resource is absent or ambiguous in installed package"
        )
    return matches[0].read_bytes()


__all__ = [
    "MAX_COMPONENT_MANIFEST_BYTES",
    "parse_component_manifest_json",
    "read_located_component_manifest",
    "verify_located_component_manifest",
]
