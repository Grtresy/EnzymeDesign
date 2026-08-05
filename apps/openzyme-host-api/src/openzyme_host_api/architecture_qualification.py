from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import inspect
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Mapping
from typing import Sequence

from .harness_owner_constraints import OWNER_CONSTRAINT_REGISTRY_ID
from .harness_owner_constraints import OWNER_CONSTRAINT_REGISTRY_RELATIVE_PATH
from .harness_owner_constraints import OWNER_CONSTRAINT_REGISTRY_SCHEMA_ID
from .harness_owner_constraints import load_harness_owner_constraint_registry


REGISTRY_SCHEMA_ID = "openzyme_v3_architecture_invariant_registry@2"
REGISTRY_ID = "openzyme_v3_architecture_invariants"
REGISTRY_RELATIVE_PATH = Path(
    "docs/v3/architecture-qualification/invariant-registry.json"
)
PROFILE_ID = "local_single_process_file_sqlite@1"
TEST_MANIFEST_SCHEMA_ID = "openzyme_v3_architecture_test_manifest@1"
QUALIFICATION_REPORT_SCHEMA_ID_V1 = "openzyme_v3_architecture_qualification_report@1"
QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID_V1 = (
    "openzyme_v3_architecture_qualification_payload@1"
)
QUALIFICATION_REPORT_SCHEMA_ID_V2 = "openzyme_v3_architecture_qualification_report@2"
QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID_V2 = (
    "openzyme_v3_architecture_qualification_payload@2"
)
QUALIFICATION_REPORT_SCHEMA_ID = "openzyme_v3_architecture_qualification_report@3"
QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID = (
    "openzyme_v3_architecture_qualification_payload@3"
)

REQUIRED_FAMILIES = (
    "authority-composition",
    "boundary-scale",
    "bounded-terminal-convergence",
    "evidence-projection",
    "identity-semantics",
    "operator-retirement",
    "reconciliation",
    "restart-fencing",
    "strategy-neutrality",
    "supervisor-progress",
    "wire-contract",
    "world-fidelity",
)

REQUIRED_P0_TRIGGERS = (
    "admission-bypass",
    "authority-drift",
    "duplicate-effect-or-approval",
    "false-success",
    "unbounded-progress",
    "unverifiable-evidence",
)

_TOP_LEVEL_FIELDS = frozenset(
    {
        "boundary_relations",
        "external_ports",
        "implementation_files",
        "invariants",
        "owner_constraint_registry",
        "p0_triggers",
        "profile",
        "registry_id",
        "required_families",
        "required_scenario_ids",
        "scenarios",
        "schema_id",
    }
)
_OWNER_CONSTRAINT_REGISTRY_FIELDS = frozenset(
    {"content_digest", "path", "registry_id", "schema_id"}
)
_PROFILE_FIELDS = frozenset(
    {
        "claims",
        "database_mode",
        "excludes",
        "process_model",
        "profile_id",
        "trust_boundary",
    }
)
_EXTERNAL_PORT_FIELDS = frozenset(
    {
        "effect_ledger_required",
        "port_id",
        "production_seams",
        "qualification_mode",
    }
)
_P0_TRIGGER_FIELDS = frozenset({"description", "trigger_id"})
_BOUNDARY_RELATION_FIELDS = frozenset({"boundary_id", "owner", "seams"})
_SYMBOL_REFERENCE_FIELDS = frozenset({"module", "source_file", "symbol"})
_SEAM_REFERENCE_FIELDS = frozenset(
    {"module", "relation", "source_file", "symbol"}
)
_INVARIANT_FIELDS = frozenset(
    {
        "contract_refs",
        "failure_class",
        "family",
        "invariant_id",
        "owner_boundary",
        "p0_trigger_ids",
        "profile_ids",
        "scenario_ids",
        "title",
    }
)
_SCENARIO_FIELDS = frozenset(
    {
        "boundary_ids",
        "budgets",
        "external_port_ids",
        "family",
        "fault_points",
        "provenance_refs",
        "scenario_id",
        "selections",
        "source_files",
        "test_selector",
    }
)
_BUDGET_FIELDS = frozenset(
    {
        "deadline_seconds",
        "max_effect_count",
        "max_event_delta",
        "max_state_version_delta",
        "max_steps",
        "max_ticks",
    }
)
_FAILURE_CLASSES = frozenset({"boundary", "integrity", "liveness", "safety"})
_QUALIFICATION_MODES = frozenset(
    {"controlled_adapter", "forbidden", "local_fault_process"}
)
_BOUNDARY_RELATIONS = frozenset({"equal", "less_than_or_equal"})
_SELECTIONS = frozenset({"full", "premerge_subset"})
_STABLE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class ArchitectureQualificationError(ValueError):
    """Base class for stable architecture-qualification failures."""

    code = "architecture_qualification_invalid"


class ArchitectureQualificationRegistryError(ArchitectureQualificationError):
    """Stable fail-closed error for registry bytes or closure."""

    code = "architecture_qualification_registry_invalid"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ArchitectureQualificationManifestError(ArchitectureQualificationError):
    """Stable fail-closed error for pytest collection closure."""

    code = "architecture_qualification_test_manifest_invalid"


class ArchitectureQualificationBoundaryError(ArchitectureQualificationError):
    """Stable fail-closed error for a symbolic product limit relation."""

    code = "architecture_qualification_boundary_invalid"


class ArchitectureQualificationReportError(ArchitectureQualificationError):
    """Stable fail-closed error for report bytes or identity."""

    code = "architecture_qualification_report_invalid"


class ArchitectureQualificationOutputError(ArchitectureQualificationError):
    """Stable fail-closed error for a qualification output target."""

    code = "architecture_qualification_output_invalid"


class ArchitectureQualificationRunError(ArchitectureQualificationError):
    """Stable fail-closed error for qualification run admission."""

    code = "architecture_qualification_run_invalid"


class ArchitectureQualificationRunActiveError(ArchitectureQualificationRunError):
    """The canonical checkout already has a kernel-held qualification run."""

    code = "architecture_qualification_run_active"


@dataclass(frozen=True, slots=True)
class LoadedArchitectureQualificationReport:
    envelope: Mapping[str, object]
    payload: Mapping[str, object]
    payload_digest: str


@dataclass(frozen=True, slots=True)
class ArchitectureQualificationVerification:
    admission_eligible: bool
    payload_digest: str
    rejection_reasons: tuple[str, ...]
    source_commit: str


@dataclass(frozen=True, slots=True)
class ValidatedQualificationOutputTarget:
    repo_root: Path
    parent: Path
    target_directory: Path


@dataclass(frozen=True, slots=True)
class ValidatedInvariantRegistry:
    payload: Mapping[str, object]
    registry_digest: str
    owner_constraint_registry_digest: str
    source_path: Path | None = None


@dataclass(frozen=True, slots=True)
class CollectedQualificationScenario:
    scenario_id: str
    family: str
    node_id: str
    source_file: str
    selections: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidatedTestManifest:
    payload: Mapping[str, object]
    test_manifest_digest: str


@dataclass(frozen=True, slots=True)
class ResolvedBoundaryRelation:
    boundary_id: str
    owner_value: int
    cases: tuple[int, int, int]
    seam_values: Mapping[str, int]


def canonical_json_bytes(payload: object) -> bytes:
    """Return the repository canonical JSON representation without a newline."""

    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArchitectureQualificationRegistryError(
            "registry contains a non-JSON or non-finite value"
        ) from exc


def canonical_json_document_bytes(payload: object) -> bytes:
    return canonical_json_bytes(payload) + b"\n"


def _strict_json_loads(content: bytes) -> object:
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ArchitectureQualificationRegistryError(
            "registry is not strict UTF-8"
        ) from exc

    def reject_constant(value: str) -> None:
        raise ArchitectureQualificationRegistryError(
            f"registry contains forbidden non-finite constant {value}"
        )

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ArchitectureQualificationRegistryError(
                    f"registry contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except ArchitectureQualificationRegistryError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ArchitectureQualificationRegistryError(
            "registry is not strict JSON"
        ) from exc


def _object(
    value: object,
    *,
    label: str,
    fields: frozenset[str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ArchitectureQualificationRegistryError(f"{label} must be an object")
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        raise ArchitectureQualificationRegistryError(
            f"{label} fields are not closed; missing={missing}, unknown={unknown}"
        )
    return value


def _array(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ArchitectureQualificationRegistryError(f"{label} must be an array")
    return value


def _text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ArchitectureQualificationRegistryError(
            f"{label} must be non-empty trimmed text"
        )
    return value


def _stable_id(value: object, *, label: str) -> str:
    text = _text(value, label=label)
    if _STABLE_ID_PATTERN.fullmatch(text) is None:
        raise ArchitectureQualificationRegistryError(
            f"{label} is not a stable lowercase id"
        )
    return text


def _sorted_unique_texts(
    value: object,
    *,
    label: str,
    allow_empty: bool,
    stable_ids: bool = False,
) -> tuple[str, ...]:
    items = _array(value, label=label)
    normalized = tuple(
        _stable_id(item, label=f"{label}[]")
        if stable_ids
        else _text(item, label=f"{label}[]")
        for item in items
    )
    if not allow_empty and not normalized:
        raise ArchitectureQualificationRegistryError(f"{label} must not be empty")
    if tuple(sorted(set(normalized))) != normalized:
        raise ArchitectureQualificationRegistryError(
            f"{label} must be sorted and unique"
        )
    return normalized


def _records_by_id(
    value: object,
    *,
    label: str,
    fields: frozenset[str],
    id_field: str,
) -> dict[str, dict[str, object]]:
    records = _array(value, label=label)
    indexed: dict[str, dict[str, object]] = {}
    ordered_ids: list[str] = []
    for index, raw_record in enumerate(records):
        record = _object(raw_record, label=f"{label}[{index}]", fields=fields)
        record_id = _stable_id(record[id_field], label=f"{label}[{index}].{id_field}")
        if record_id in indexed:
            raise ArchitectureQualificationRegistryError(
                f"{label} contains duplicate id {record_id!r}"
            )
        indexed[record_id] = record
        ordered_ids.append(record_id)
    if ordered_ids != sorted(ordered_ids):
        raise ArchitectureQualificationRegistryError(f"{label} must be sorted by id")
    return indexed


def _source_file(
    value: object,
    *,
    label: str,
    repo_root: Path,
) -> str:
    text = _text(value, label=label)
    pure = PurePosixPath(text)
    if pure.is_absolute() or pure.as_posix() != text or ".." in pure.parts:
        raise ArchitectureQualificationRegistryError(
            f"{label} must be a normalized repository-relative path"
        )
    candidate = repo_root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ArchitectureQualificationRegistryError(
            f"{label} does not resolve to a readable regular source file: {text}"
        )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo_root)
        with resolved.open("rb") as handle:
            handle.read(1)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ArchitectureQualificationRegistryError(
            f"{label} escapes or cannot be read from the repository: {text}"
        ) from exc
    return text


def _source_files(
    value: object,
    *,
    label: str,
    repo_root: Path,
    allow_empty: bool,
) -> tuple[str, ...]:
    raw_items = _array(value, label=label)
    items = tuple(
        _source_file(item, label=f"{label}[]", repo_root=repo_root)
        for item in raw_items
    )
    if not allow_empty and not items:
        raise ArchitectureQualificationRegistryError(f"{label} must not be empty")
    if tuple(sorted(set(items))) != items:
        raise ArchitectureQualificationRegistryError(
            f"{label} must be sorted and unique"
        )
    return items


def _validate_profile(value: object) -> None:
    profile = _object(value, label="profile", fields=_PROFILE_FIELDS)
    if profile["profile_id"] != PROFILE_ID:
        raise ArchitectureQualificationRegistryError(
            f"profile.profile_id must be {PROFILE_ID!r}"
        )
    if profile["trust_boundary"] != "trusted_host":
        raise ArchitectureQualificationRegistryError(
            "profile.trust_boundary must be 'trusted_host'"
        )
    if profile["database_mode"] != "file_sqlite":
        raise ArchitectureQualificationRegistryError(
            "profile.database_mode must be 'file_sqlite'"
        )
    if profile["process_model"] != "single_process":
        raise ArchitectureQualificationRegistryError(
            "profile.process_model must be 'single_process'"
        )
    _sorted_unique_texts(
        profile["claims"], label="profile.claims", allow_empty=False
    )
    _sorted_unique_texts(
        profile["excludes"], label="profile.excludes", allow_empty=False
    )


def _validate_external_ports(value: object) -> dict[str, dict[str, object]]:
    ports = _records_by_id(
        value,
        label="external_ports",
        fields=_EXTERNAL_PORT_FIELDS,
        id_field="port_id",
    )
    for port_id, port in ports.items():
        seams = _sorted_unique_texts(
            port["production_seams"],
            label=f"external_ports[{port_id}].production_seams",
            allow_empty=False,
        )
        del seams
        mode = _text(
            port["qualification_mode"],
            label=f"external_ports[{port_id}].qualification_mode",
        )
        if mode not in _QUALIFICATION_MODES:
            raise ArchitectureQualificationRegistryError(
                f"external port {port_id!r} has unknown qualification mode"
            )
        ledger_required = port["effect_ledger_required"]
        if not isinstance(ledger_required, bool):
            raise ArchitectureQualificationRegistryError(
                f"external port {port_id!r} effect_ledger_required must be bool"
            )
        if mode == "controlled_adapter" and not ledger_required:
            raise ArchitectureQualificationRegistryError(
                f"controlled external port {port_id!r} requires an effect ledger"
            )
    return ports


def _validate_p0_triggers(value: object) -> dict[str, dict[str, object]]:
    triggers = _records_by_id(
        value,
        label="p0_triggers",
        fields=_P0_TRIGGER_FIELDS,
        id_field="trigger_id",
    )
    if tuple(triggers) != REQUIRED_P0_TRIGGERS:
        raise ArchitectureQualificationRegistryError(
            "p0_triggers must define the exact schema-v1 automatic trigger set"
        )
    for trigger_id, trigger in triggers.items():
        _text(
            trigger["description"],
            label=f"p0_triggers[{trigger_id}].description",
        )
    return triggers


def _validate_symbol_reference(
    value: object,
    *,
    label: str,
    fields: frozenset[str],
    repo_root: Path,
    allow_relation: bool,
) -> dict[str, object]:
    reference = _object(value, label=label, fields=fields)
    _text(reference["module"], label=f"{label}.module")
    _text(reference["symbol"], label=f"{label}.symbol")
    _source_file(reference["source_file"], label=f"{label}.source_file", repo_root=repo_root)
    if allow_relation:
        relation = _text(reference["relation"], label=f"{label}.relation")
        if relation not in _BOUNDARY_RELATIONS:
            raise ArchitectureQualificationRegistryError(
                f"{label}.relation is unknown"
            )
    return reference


def _validate_boundary_relations(
    value: object,
    *,
    repo_root: Path,
) -> dict[str, dict[str, object]]:
    boundaries = _records_by_id(
        value,
        label="boundary_relations",
        fields=_BOUNDARY_RELATION_FIELDS,
        id_field="boundary_id",
    )
    for boundary_id, boundary in boundaries.items():
        _validate_symbol_reference(
            boundary["owner"],
            label=f"boundary_relations[{boundary_id}].owner",
            fields=_SYMBOL_REFERENCE_FIELDS,
            repo_root=repo_root,
            allow_relation=False,
        )
        raw_seams = _array(
            boundary["seams"], label=f"boundary_relations[{boundary_id}].seams"
        )
        seam_identities: list[str] = []
        for index, raw_seam in enumerate(raw_seams):
            seam = _validate_symbol_reference(
                raw_seam,
                label=f"boundary_relations[{boundary_id}].seams[{index}]",
                fields=_SEAM_REFERENCE_FIELDS,
                repo_root=repo_root,
                allow_relation=True,
            )
            seam_identities.append(f"{seam['module']}:{seam['symbol']}")
        if not seam_identities:
            raise ArchitectureQualificationRegistryError(
                f"boundary relation {boundary_id!r} must declare at least one seam"
            )
        if seam_identities != sorted(set(seam_identities)):
            raise ArchitectureQualificationRegistryError(
                f"boundary relation {boundary_id!r} seams must be sorted and unique"
            )
    return boundaries


def _validate_invariants(
    value: object,
    *,
    repo_root: Path,
    p0_trigger_ids: frozenset[str],
) -> dict[str, dict[str, object]]:
    invariants = _records_by_id(
        value,
        label="invariants",
        fields=_INVARIANT_FIELDS,
        id_field="invariant_id",
    )
    for invariant_id, invariant in invariants.items():
        family = _stable_id(
            invariant["family"], label=f"invariants[{invariant_id}].family"
        )
        if family not in REQUIRED_FAMILIES:
            raise ArchitectureQualificationRegistryError(
                f"invariant {invariant_id!r} has unknown family {family!r}"
            )
        _text(invariant["title"], label=f"invariants[{invariant_id}].title")
        _stable_id(
            invariant["owner_boundary"],
            label=f"invariants[{invariant_id}].owner_boundary",
        )
        _source_files(
            invariant["contract_refs"],
            label=f"invariants[{invariant_id}].contract_refs",
            repo_root=repo_root,
            allow_empty=False,
        )
        profile_ids = _sorted_unique_texts(
            invariant["profile_ids"],
            label=f"invariants[{invariant_id}].profile_ids",
            allow_empty=False,
        )
        if profile_ids != (PROFILE_ID,):
            raise ArchitectureQualificationRegistryError(
                f"invariant {invariant_id!r} must bind the exact local profile"
            )
        failure_class = _stable_id(
            invariant["failure_class"],
            label=f"invariants[{invariant_id}].failure_class",
        )
        if failure_class not in _FAILURE_CLASSES:
            raise ArchitectureQualificationRegistryError(
                f"invariant {invariant_id!r} has unknown failure class"
            )
        trigger_ids = frozenset(
            _sorted_unique_texts(
                invariant["p0_trigger_ids"],
                label=f"invariants[{invariant_id}].p0_trigger_ids",
                allow_empty=False,
                stable_ids=True,
            )
        )
        if not trigger_ids <= p0_trigger_ids:
            raise ArchitectureQualificationRegistryError(
                f"invariant {invariant_id!r} references an unknown P0 trigger"
            )
        _sorted_unique_texts(
            invariant["scenario_ids"],
            label=f"invariants[{invariant_id}].scenario_ids",
            allow_empty=False,
            stable_ids=True,
        )
    return invariants


def _validate_budget(value: object, *, scenario_id: str) -> None:
    budget = _object(
        value,
        label=f"scenarios[{scenario_id}].budgets",
        fields=_BUDGET_FIELDS,
    )
    for field in sorted(_BUDGET_FIELDS):
        amount = budget[field]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ArchitectureQualificationRegistryError(
                f"scenarios[{scenario_id}].budgets.{field} must be a non-negative int"
            )
    if budget["deadline_seconds"] <= 0:
        raise ArchitectureQualificationRegistryError(
            f"scenarios[{scenario_id}].budgets.deadline_seconds must be positive"
        )


def _validate_scenarios(
    value: object,
    *,
    repo_root: Path,
    external_port_ids: frozenset[str],
    boundary_ids: frozenset[str],
) -> dict[str, dict[str, object]]:
    scenarios = _records_by_id(
        value,
        label="scenarios",
        fields=_SCENARIO_FIELDS,
        id_field="scenario_id",
    )
    for scenario_id, scenario in scenarios.items():
        family = _stable_id(
            scenario["family"], label=f"scenarios[{scenario_id}].family"
        )
        if family not in REQUIRED_FAMILIES:
            raise ArchitectureQualificationRegistryError(
                f"scenario {scenario_id!r} has unknown family {family!r}"
            )
        source_files = _source_files(
            scenario["source_files"],
            label=f"scenarios[{scenario_id}].source_files",
            repo_root=repo_root,
            allow_empty=False,
        )
        selector = _text(
            scenario["test_selector"],
            label=f"scenarios[{scenario_id}].test_selector",
        )
        selector_source, separator, _ = selector.partition("::")
        if not separator or selector_source not in source_files:
            raise ArchitectureQualificationRegistryError(
                f"scenario {scenario_id!r} selector must name one declared source file"
            )
        scenario_ports = frozenset(
            _sorted_unique_texts(
                scenario["external_port_ids"],
                label=f"scenarios[{scenario_id}].external_port_ids",
                allow_empty=True,
                stable_ids=True,
            )
        )
        if not scenario_ports <= external_port_ids:
            raise ArchitectureQualificationRegistryError(
                f"scenario {scenario_id!r} references an unknown external port"
            )
        scenario_boundaries = frozenset(
            _sorted_unique_texts(
                scenario["boundary_ids"],
                label=f"scenarios[{scenario_id}].boundary_ids",
                allow_empty=True,
                stable_ids=True,
            )
        )
        if not scenario_boundaries <= boundary_ids:
            raise ArchitectureQualificationRegistryError(
                f"scenario {scenario_id!r} references an unknown boundary"
            )
        _sorted_unique_texts(
            scenario["fault_points"],
            label=f"scenarios[{scenario_id}].fault_points",
            allow_empty=True,
            stable_ids=True,
        )
        _sorted_unique_texts(
            scenario["provenance_refs"],
            label=f"scenarios[{scenario_id}].provenance_refs",
            allow_empty=True,
        )
        selections = frozenset(
            _sorted_unique_texts(
                scenario["selections"],
                label=f"scenarios[{scenario_id}].selections",
                allow_empty=False,
                stable_ids=True,
            )
        )
        if "full" not in selections or not selections <= _SELECTIONS:
            raise ArchitectureQualificationRegistryError(
                f"scenario {scenario_id!r} must belong to full and only known selections"
            )
        _validate_budget(scenario["budgets"], scenario_id=scenario_id)
    return scenarios


def _validate_invariant_scenario_closure(
    invariants: Mapping[str, Mapping[str, object]],
    scenarios: Mapping[str, Mapping[str, object]],
) -> None:
    scenario_owners: dict[str, list[str]] = {scenario_id: [] for scenario_id in scenarios}
    for invariant_id, invariant in invariants.items():
        scenario_ids = _sorted_unique_texts(
            invariant["scenario_ids"],
            label=f"invariants[{invariant_id}].scenario_ids",
            allow_empty=False,
            stable_ids=True,
        )
        for scenario_id in scenario_ids:
            scenario = scenarios.get(scenario_id)
            if scenario is None:
                raise ArchitectureQualificationRegistryError(
                    f"invariant {invariant_id!r} references missing scenario {scenario_id!r}"
                )
            if scenario["family"] != invariant["family"]:
                raise ArchitectureQualificationRegistryError(
                    f"scenario {scenario_id!r} crosses invariant family ownership"
                )
            scenario_owners[scenario_id].append(invariant_id)
    orphaned = sorted(
        scenario_id for scenario_id, owners in scenario_owners.items() if not owners
    )
    if orphaned:
        raise ArchitectureQualificationRegistryError(
            f"registry contains orphan scenarios: {orphaned}"
        )


def validate_invariant_registry_bytes(
    content: bytes,
    *,
    repo_root: Path,
    source_path: Path | None = None,
) -> ValidatedInvariantRegistry:
    root = repo_root.resolve(strict=True)
    if not root.is_dir():
        raise ArchitectureQualificationRegistryError("repo_root must be a directory")
    payload = _strict_json_loads(content)
    registry = _object(payload, label="registry", fields=_TOP_LEVEL_FIELDS)
    if content != canonical_json_document_bytes(registry):
        raise ArchitectureQualificationRegistryError(
            "registry bytes are not canonical JSON followed by one LF"
        )
    if registry["schema_id"] != REGISTRY_SCHEMA_ID:
        raise ArchitectureQualificationRegistryError(
            f"registry.schema_id must be {REGISTRY_SCHEMA_ID!r}"
        )
    if registry["registry_id"] != REGISTRY_ID:
        raise ArchitectureQualificationRegistryError(
            f"registry.registry_id must be {REGISTRY_ID!r}"
        )
    owner_binding = _object(
        registry["owner_constraint_registry"],
        label="owner_constraint_registry",
        fields=_OWNER_CONSTRAINT_REGISTRY_FIELDS,
    )
    if owner_binding["path"] != OWNER_CONSTRAINT_REGISTRY_RELATIVE_PATH.as_posix():
        raise ArchitectureQualificationRegistryError(
            "owner_constraint_registry.path does not name the canonical registry"
        )
    if owner_binding["schema_id"] != OWNER_CONSTRAINT_REGISTRY_SCHEMA_ID:
        raise ArchitectureQualificationRegistryError(
            "owner_constraint_registry.schema_id is unsupported"
        )
    if owner_binding["registry_id"] != OWNER_CONSTRAINT_REGISTRY_ID:
        raise ArchitectureQualificationRegistryError(
            "owner_constraint_registry.registry_id is unsupported"
        )
    owner_registry = load_harness_owner_constraint_registry(root)
    if owner_binding["content_digest"] != owner_registry.registry_digest:
        raise ArchitectureQualificationRegistryError(
            "owner_constraint_registry.content_digest differs from canonical bytes"
        )
    _validate_profile(registry["profile"])
    required_families = _sorted_unique_texts(
        registry["required_families"],
        label="required_families",
        allow_empty=False,
        stable_ids=True,
    )
    if required_families != REQUIRED_FAMILIES:
        raise ArchitectureQualificationRegistryError(
            "required_families must equal the exact schema-v2 family set"
        )
    _source_files(
        registry["implementation_files"],
        label="implementation_files",
        repo_root=root,
        allow_empty=False,
    )
    external_ports = _validate_external_ports(registry["external_ports"])
    p0_triggers = _validate_p0_triggers(registry["p0_triggers"])
    boundaries = _validate_boundary_relations(
        registry["boundary_relations"], repo_root=root
    )
    invariants = _validate_invariants(
        registry["invariants"],
        repo_root=root,
        p0_trigger_ids=frozenset(p0_triggers),
    )
    scenarios = _validate_scenarios(
        registry["scenarios"],
        repo_root=root,
        external_port_ids=frozenset(external_ports),
        boundary_ids=frozenset(boundaries),
    )
    actual_families = tuple(sorted({str(item["family"]) for item in invariants.values()}))
    if actual_families != REQUIRED_FAMILIES:
        raise ArchitectureQualificationRegistryError(
            "invariants do not cover the exact required family set"
        )
    required_scenario_ids = _sorted_unique_texts(
        registry["required_scenario_ids"],
        label="required_scenario_ids",
        allow_empty=False,
        stable_ids=True,
    )
    if required_scenario_ids != tuple(scenarios):
        raise ArchitectureQualificationRegistryError(
            "required_scenario_ids must equal the exact registered scenario set"
        )
    _validate_invariant_scenario_closure(invariants, scenarios)
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    return ValidatedInvariantRegistry(
        payload=registry,
        registry_digest=digest,
        owner_constraint_registry_digest=owner_registry.registry_digest,
        source_path=source_path,
    )


def load_invariant_registry(*, repo_root: Path) -> ValidatedInvariantRegistry:
    root = repo_root.resolve(strict=True)
    registry_path = root / REGISTRY_RELATIVE_PATH
    if registry_path.is_symlink() or not registry_path.is_file():
        raise ArchitectureQualificationRegistryError(
            f"canonical registry is missing: {REGISTRY_RELATIVE_PATH.as_posix()}"
        )
    try:
        content = registry_path.read_bytes()
    except OSError as exc:
        raise ArchitectureQualificationRegistryError(
            "canonical registry cannot be read"
        ) from exc
    return validate_invariant_registry_bytes(
        content,
        repo_root=root,
        source_path=registry_path,
    )


def _digest_file(relative_path: str, *, repo_root: Path) -> dict[str, str]:
    normalized = _source_file(
        relative_path,
        label="manifest source file",
        repo_root=repo_root,
    )
    content = (repo_root / normalized).read_bytes()
    return {
        "content_digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
        "path": normalized,
    }


def _digest_file_set(
    paths: Sequence[str],
    *,
    repo_root: Path,
) -> list[dict[str, str]]:
    return [_digest_file(path, repo_root=repo_root) for path in sorted(set(paths))]


def build_test_manifest(
    registry: ValidatedInvariantRegistry,
    *,
    collected_scenarios: Sequence[CollectedQualificationScenario],
    repo_root: Path,
) -> ValidatedTestManifest:
    """Close stable pytest scenario ids over current source and implementation bytes."""

    root = repo_root.resolve(strict=True)
    raw_scenarios = registry.payload.get("scenarios")
    if not isinstance(raw_scenarios, list):
        raise ArchitectureQualificationManifestError(
            "validated registry lost its scenario records"
        )
    registered: dict[str, Mapping[str, object]] = {}
    for raw_scenario in raw_scenarios:
        if not isinstance(raw_scenario, dict):
            raise ArchitectureQualificationManifestError(
                "validated registry contains a non-object scenario"
            )
        scenario_id = str(raw_scenario.get("scenario_id") or "")
        registered[scenario_id] = raw_scenario

    collected: dict[str, CollectedQualificationScenario] = {}
    node_ids: set[str] = set()
    for scenario in collected_scenarios:
        if scenario.scenario_id in collected:
            raise ArchitectureQualificationManifestError(
                f"scenario {scenario.scenario_id!r} was collected more than once"
            )
        if scenario.node_id in node_ids:
            raise ArchitectureQualificationManifestError(
                f"pytest node {scenario.node_id!r} owns more than one scenario id"
            )
        collected[scenario.scenario_id] = scenario
        node_ids.add(scenario.node_id)

    missing = sorted(set(registered) - set(collected))
    unknown = sorted(set(collected) - set(registered))
    if missing or unknown:
        raise ArchitectureQualificationManifestError(
            f"pytest collection drifted; missing={missing}, unknown={unknown}"
        )

    manifest_scenarios: list[dict[str, object]] = []
    for scenario_id in sorted(registered):
        expected = registered[scenario_id]
        actual = collected[scenario_id]
        expected_family = str(expected["family"])
        expected_selector = str(expected["test_selector"])
        expected_sources = tuple(str(item) for item in expected["source_files"])
        expected_selections = tuple(str(item) for item in expected["selections"])
        if actual.family != expected_family:
            raise ArchitectureQualificationManifestError(
                f"scenario {scenario_id!r} family drifted"
            )
        if actual.node_id != expected_selector:
            raise ArchitectureQualificationManifestError(
                f"scenario {scenario_id!r} selector drifted"
            )
        if actual.source_file not in expected_sources:
            raise ArchitectureQualificationManifestError(
                f"scenario {scenario_id!r} source file drifted"
            )
        if actual.selections != expected_selections:
            raise ArchitectureQualificationManifestError(
                f"scenario {scenario_id!r} selections drifted"
            )
        manifest_scenarios.append(
            {
                "collected_node_id": actual.node_id,
                "family": actual.family,
                "scenario_id": scenario_id,
                "selections": list(actual.selections),
                "source_files": _digest_file_set(
                    expected_sources,
                    repo_root=root,
                ),
            }
        )

    raw_invariants = registry.payload.get("invariants")
    if not isinstance(raw_invariants, list):
        raise ArchitectureQualificationManifestError(
            "validated registry lost its invariant records"
        )
    contract_refs: list[str] = []
    for invariant in raw_invariants:
        if not isinstance(invariant, dict) or not isinstance(
            invariant.get("contract_refs"), list
        ):
            raise ArchitectureQualificationManifestError(
                "validated registry lost invariant contract refs"
            )
        contract_refs.extend(str(item) for item in invariant["contract_refs"])
    implementation_files = registry.payload.get("implementation_files")
    if not isinstance(implementation_files, list):
        raise ArchitectureQualificationManifestError(
            "validated registry lost implementation files"
        )

    manifest: dict[str, object] = {
        "contract_files": _digest_file_set(contract_refs, repo_root=root),
        "implementation_files": _digest_file_set(
            [str(item) for item in implementation_files],
            repo_root=root,
        ),
        "registry_digest": registry.registry_digest,
        "scenarios": manifest_scenarios,
        "schema_id": TEST_MANIFEST_SCHEMA_ID,
    }
    manifest_bytes = canonical_json_document_bytes(manifest)
    return ValidatedTestManifest(
        payload=manifest,
        test_manifest_digest=(
            f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"
        ),
    )


def _load_symbol_value(
    reference: Mapping[str, object],
    *,
    repo_root: Path,
    label: str,
) -> int:
    module_name = str(reference["module"])
    symbol_name = str(reference["symbol"])
    source_file = str(reference["source_file"])
    if any(not part.isidentifier() for part in module_name.split(".")):
        raise ArchitectureQualificationBoundaryError(
            f"{label} has an invalid module path"
        )
    if any(not part.isidentifier() for part in symbol_name.split(".")):
        raise ArchitectureQualificationBoundaryError(
            f"{label} has an invalid symbol path"
        )
    try:
        module = importlib.import_module(module_name)
    except (ImportError, RuntimeError, ValueError) as exc:
        raise ArchitectureQualificationBoundaryError(
            f"{label} module cannot be imported"
        ) from exc
    module_source = inspect.getsourcefile(module)
    if module_source is None:
        raise ArchitectureQualificationBoundaryError(
            f"{label} module has no source identity"
        )
    try:
        actual_source = Path(module_source).resolve(strict=True).relative_to(repo_root)
    except (OSError, ValueError) as exc:
        raise ArchitectureQualificationBoundaryError(
            f"{label} module source is outside the repository"
        ) from exc
    if actual_source.as_posix() != source_file:
        raise ArchitectureQualificationBoundaryError(
            f"{label} module source drifted from the registry"
        )
    value: object = module
    try:
        for part in symbol_name.split("."):
            value = getattr(value, part)
    except AttributeError as exc:
        raise ArchitectureQualificationBoundaryError(
            f"{label} symbol cannot be resolved"
        ) from exc
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ArchitectureQualificationBoundaryError(
            f"{label} symbol must own a positive integer limit"
        )
    return value


def resolve_boundary_relation(
    registry: ValidatedInvariantRegistry,
    *,
    boundary_id: str,
    repo_root: Path,
) -> ResolvedBoundaryRelation:
    raw_boundaries = registry.payload.get("boundary_relations")
    if not isinstance(raw_boundaries, list):
        raise ArchitectureQualificationBoundaryError(
            "validated registry lost boundary relations"
        )
    boundary = next(
        (
            item
            for item in raw_boundaries
            if isinstance(item, dict) and item.get("boundary_id") == boundary_id
        ),
        None,
    )
    if boundary is None:
        raise ArchitectureQualificationBoundaryError(
            f"boundary {boundary_id!r} is not registered"
        )
    root = repo_root.resolve(strict=True)
    owner = boundary.get("owner")
    seams = boundary.get("seams")
    if not isinstance(owner, dict) or not isinstance(seams, list):
        raise ArchitectureQualificationBoundaryError(
            f"boundary {boundary_id!r} lost its closed schema"
        )
    owner_value = _load_symbol_value(
        owner,
        repo_root=root,
        label=f"boundary {boundary_id!r} owner",
    )
    seam_values: dict[str, int] = {}
    for index, raw_seam in enumerate(seams):
        if not isinstance(raw_seam, dict):
            raise ArchitectureQualificationBoundaryError(
                f"boundary {boundary_id!r} seam {index} is invalid"
            )
        seam_value = _load_symbol_value(
            raw_seam,
            repo_root=root,
            label=f"boundary {boundary_id!r} seam {index}",
        )
        identity = f"{raw_seam['module']}:{raw_seam['symbol']}"
        relation = raw_seam.get("relation")
        if relation == "equal" and seam_value != owner_value:
            raise ArchitectureQualificationBoundaryError(
                f"boundary {boundary_id!r} equality drifted at {identity}"
            )
        if relation == "less_than_or_equal" and seam_value > owner_value:
            raise ArchitectureQualificationBoundaryError(
                f"boundary {boundary_id!r} upper relation drifted at {identity}"
            )
        seam_values[identity] = seam_value
    return ResolvedBoundaryRelation(
        boundary_id=boundary_id,
        owner_value=owner_value,
        cases=(owner_value - 1, owner_value, owner_value + 1),
        seam_values=seam_values,
    )


def collect_architecture_source_identity(
    *,
    repo_root: Path,
) -> Mapping[str, object]:
    from .architecture_qualification_report import collect_source_identity

    return collect_source_identity(repo_root=repo_root)


def collect_architecture_qualification_implementation_identity(
    *,
    repo_root: Path,
    runner_path: Path,
    test_manifest: ValidatedTestManifest,
) -> Mapping[str, object]:
    from .architecture_qualification_report import collect_implementation_identity

    return collect_implementation_identity(
        repo_root=repo_root,
        runner_path=runner_path,
        test_manifest=test_manifest.payload,
    )


def build_architecture_qualification_report(
    *,
    repo_root: Path,
    runner_path: Path,
    mode: str,
    command: Sequence[str],
    registry: ValidatedInvariantRegistry,
    test_manifest: ValidatedTestManifest,
    source_identity: Mapping[str, object],
    terminal_source_identity: Mapping[str, object],
    source_revalidations: Sequence[Mapping[str, object]],
    process_receipts: Sequence[Mapping[str, object]],
    run_failure: Mapping[str, object] | None,
    not_run_scenario_ids: Sequence[str],
    harness_result: Mapping[str, object],
    scenario_results: Sequence[Mapping[str, object]],
    implementation_identity: Mapping[str, object] | None = None,
) -> LoadedArchitectureQualificationReport:
    from .architecture_qualification_report import build_report

    return build_report(
        repo_root=repo_root,
        runner_path=runner_path,
        mode=mode,
        command=command,
        registry=registry,
        test_manifest=test_manifest,
        source_identity=source_identity,
        terminal_source_identity=terminal_source_identity,
        source_revalidations=source_revalidations,
        process_receipts=process_receipts,
        run_failure=run_failure,
        not_run_scenario_ids=not_run_scenario_ids,
        harness_result=harness_result,
        scenario_results=scenario_results,
        implementation_identity=implementation_identity,
    )


def load_architecture_qualification_report_bytes(
    content: bytes,
) -> LoadedArchitectureQualificationReport:
    from .architecture_qualification_report import load_report_bytes

    return load_report_bytes(content)


def load_architecture_qualification_report(
    path: Path,
) -> LoadedArchitectureQualificationReport:
    from .architecture_qualification_report import load_report

    return load_report(path)


def publish_architecture_qualification_report(
    report: LoadedArchitectureQualificationReport,
    *,
    output_directory: Path,
    repo_root: Path,
) -> Path:
    from .architecture_qualification_report import publish_report

    return publish_report(
        report,
        output_directory=output_directory,
        repo_root=repo_root,
    )


def validate_architecture_qualification_output_target(
    *,
    output_directory: Path,
    repo_root: Path,
) -> ValidatedQualificationOutputTarget:
    from .architecture_qualification_report import validate_output_target

    return validate_output_target(
        output_directory=output_directory,
        repo_root=repo_root,
    )


def verify_architecture_qualification_report(
    report: LoadedArchitectureQualificationReport | Path | bytes,
    *,
    repo_root: Path,
    runner_path: Path,
) -> ArchitectureQualificationVerification:
    from .architecture_qualification_report import verify_report

    return verify_report(
        report,
        repo_root=repo_root,
        runner_path=runner_path,
    )


__all__ = [
    "ArchitectureQualificationError",
    "ArchitectureQualificationBoundaryError",
    "ArchitectureQualificationManifestError",
    "ArchitectureQualificationOutputError",
    "ArchitectureQualificationReportError",
    "ArchitectureQualificationRegistryError",
    "ArchitectureQualificationRunActiveError",
    "ArchitectureQualificationRunError",
    "ArchitectureQualificationVerification",
    "CollectedQualificationScenario",
    "LoadedArchitectureQualificationReport",
    "PROFILE_ID",
    "QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID",
    "QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID_V1",
    "QUALIFICATION_REPORT_PAYLOAD_SCHEMA_ID_V2",
    "QUALIFICATION_REPORT_SCHEMA_ID",
    "QUALIFICATION_REPORT_SCHEMA_ID_V1",
    "QUALIFICATION_REPORT_SCHEMA_ID_V2",
    "REGISTRY_ID",
    "REGISTRY_RELATIVE_PATH",
    "REGISTRY_SCHEMA_ID",
    "REQUIRED_FAMILIES",
    "REQUIRED_P0_TRIGGERS",
    "ResolvedBoundaryRelation",
    "TEST_MANIFEST_SCHEMA_ID",
    "ValidatedInvariantRegistry",
    "ValidatedQualificationOutputTarget",
    "ValidatedTestManifest",
    "build_architecture_qualification_report",
    "build_test_manifest",
    "canonical_json_bytes",
    "canonical_json_document_bytes",
    "collect_architecture_source_identity",
    "collect_architecture_qualification_implementation_identity",
    "load_architecture_qualification_report",
    "load_architecture_qualification_report_bytes",
    "load_invariant_registry",
    "publish_architecture_qualification_report",
    "resolve_boundary_relation",
    "validate_invariant_registry_bytes",
    "validate_architecture_qualification_output_target",
    "verify_architecture_qualification_report",
]
