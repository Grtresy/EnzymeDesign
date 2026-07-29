"""Versioned, closed configuration for the repository test gate."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .model import sha256_digest

CONFIG_SCHEMA_ID = "openzyme_test_gate_config@1"
SUPPORTED_PROFILE_IDS = (
    "focused_diagnostic",
    "affected_scope_diagnostic",
    "mainline_authoritative",
)
FORBIDDEN_DISPATCH_PROFILE_IDS = ("architecture_admission", "live_campaign")
LEGACY_MAINLINE_STAGE_ORDER = (
    "ruff_source",
    "ruff_compatibility_audit",
    "compatibility_audit",
    "architecture_qualification_premerge",
    "general_non_live_pytest",
    "web_ui_test",
    "web_ui_build",
)
RESOURCE_CLASSES = (
    "parallel_pure",
    "parallel_temp_root",
    "bounded_service",
    "serial_unknown",
    "serial_file_sqlite",
    "serial_global_env",
    "serial_process_signal",
    "serial_qualification",
    "live_external",
)
EXPECTED_FORBIDDEN_NON_LIVE_MARKERS = (
    "integration",
    "live_llm",
    "live_tavily",
    "live_hpc",
    "live_e2e",
    "seeded_live_smoke",
    "quality_eval",
)


class ConfigError(ValueError):
    """Raised when test-gate configuration is not closed and valid."""


@dataclass(frozen=True)
class EvidencePolicy:
    repository_plane_only: bool
    requires_checkout_external_output_root: bool
    product_state_writes: bool


@dataclass(frozen=True)
class ResourcePolicy:
    default_class: str
    closed_classes: tuple[str, ...]
    parallel_eligible_classes: tuple[str, ...]


@dataclass(frozen=True)
class PytestContract:
    marker_expression: str
    allowed_non_live_markers: tuple[str, ...]
    forbidden_non_live_markers: tuple[str, ...]
    architecture_scenario_marker: str


@dataclass(frozen=True)
class EnvironmentPolicy:
    id: str
    unset: tuple[str, ...]
    set_values: tuple[tuple[str, str], ...]
    forbidden_markers: tuple[str, ...]


@dataclass(frozen=True)
class StageDefinition:
    id: str
    argv: tuple[str, ...]
    cwd: str
    environment_policy: str
    deadline_seconds: int
    resource_class: str
    qualification_mode: str | None = None


@dataclass(frozen=True)
class ProfileDefinition:
    id: str
    stage_ids: tuple[str, ...]
    authoritative: bool
    admission_eligible: bool
    live_eligible: bool
    summary: str


@dataclass(frozen=True)
class TestGateConfig:
    schema_id: str
    digest: str
    worker_hard_max: int
    supported_profiles: tuple[str, ...]
    forbidden_dispatch_profiles: tuple[str, ...]
    evidence_policy: EvidencePolicy
    resource_policy: ResourcePolicy
    pytest_contract: PytestContract
    environment_policies: tuple[EnvironmentPolicy, ...]
    stages: tuple[StageDefinition, ...]
    profiles: tuple[ProfileDefinition, ...]

    def stage(self, stage_id: str) -> StageDefinition:
        for stage in self.stages:
            if stage.id == stage_id:
                return stage
        raise ConfigError(f"unknown configured stage: {stage_id!r}")

    def environment_policy(self, policy_id: str) -> EnvironmentPolicy:
        for policy in self.environment_policies:
            if policy.id == policy_id:
                return policy
        raise ConfigError(f"unknown environment policy: {policy_id!r}")

    def profile(self, profile_id: str) -> ProfileDefinition:
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        raise ConfigError(f"unknown test-gate profile: {profile_id!r}")


def _closed_mapping(
    value: Any,
    *,
    context: str,
    required: set[str],
    optional: set[str] | None = None,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{context} must be a table")
    optional = optional or set()
    actual = set(value)
    missing = sorted(required - actual)
    unknown = sorted(actual - required - optional)
    if missing:
        raise ConfigError(f"{context} is missing fields: {', '.join(missing)}")
    if unknown:
        raise ConfigError(f"{context} has unknown fields: {', '.join(unknown)}")
    return value


def _string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{context} must be a nonempty string")
    return value


def _boolean(value: Any, *, context: str) -> bool:
    if type(value) is not bool:
        raise ConfigError(f"{context} must be a boolean")
    return value


def _positive_int(value: Any, *, context: str) -> int:
    if type(value) is not int or value <= 0:
        raise ConfigError(f"{context} must be a positive integer")
    return value


def _string_tuple(value: Any, *, context: str, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"{context} must be an array")
    result = tuple(_string(item, context=f"{context}[]") for item in value)
    if not allow_empty and not result:
        raise ConfigError(f"{context} must not be empty")
    if len(result) != len(set(result)):
        raise ConfigError(f"{context} must not contain duplicates")
    return result


def _parse_environment_policies(value: Any) -> tuple[EnvironmentPolicy, ...]:
    if not isinstance(value, dict) or not value:
        raise ConfigError("environment_policies must be a nonempty table")
    policies: list[EnvironmentPolicy] = []
    for policy_id in sorted(value):
        _string(policy_id, context="environment policy id")
        raw = _closed_mapping(
            value[policy_id],
            context=f"environment_policies.{policy_id}",
            required={"unset", "set", "forbidden_markers"},
        )
        set_values = raw["set"]
        if not isinstance(set_values, dict):
            raise ConfigError(f"environment_policies.{policy_id}.set must be a table")
        normalized_set = tuple(
            (
                _string(key, context=f"environment_policies.{policy_id}.set key"),
                _string(
                    set_values[key],
                    context=f"environment_policies.{policy_id}.set.{key}",
                ),
            )
            for key in sorted(set_values)
        )
        policies.append(
            EnvironmentPolicy(
                id=policy_id,
                unset=_string_tuple(
                    raw["unset"],
                    context=f"environment_policies.{policy_id}.unset",
                ),
                set_values=normalized_set,
                forbidden_markers=_string_tuple(
                    raw["forbidden_markers"],
                    context=f"environment_policies.{policy_id}.forbidden_markers",
                    allow_empty=False,
                ),
            )
        )
    return tuple(policies)


def _parse_stages(value: Any) -> tuple[StageDefinition, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError("stages must be a nonempty array of tables")
    stages: list[StageDefinition] = []
    for index, item in enumerate(value):
        raw = _closed_mapping(
            item,
            context=f"stages[{index}]",
            required={
                "id",
                "argv",
                "cwd",
                "environment_policy",
                "deadline_seconds",
                "resource_class",
            },
            optional={"qualification_mode"},
        )
        qualification_mode = raw.get("qualification_mode")
        if qualification_mode is not None:
            qualification_mode = _string(
                qualification_mode,
                context=f"stages[{index}].qualification_mode",
            )
        stages.append(
            StageDefinition(
                id=_string(raw["id"], context=f"stages[{index}].id"),
                argv=_string_tuple(
                    raw["argv"],
                    context=f"stages[{index}].argv",
                    allow_empty=False,
                ),
                cwd=_string(raw["cwd"], context=f"stages[{index}].cwd"),
                environment_policy=_string(
                    raw["environment_policy"],
                    context=f"stages[{index}].environment_policy",
                ),
                deadline_seconds=_positive_int(
                    raw["deadline_seconds"],
                    context=f"stages[{index}].deadline_seconds",
                ),
                resource_class=_string(
                    raw["resource_class"],
                    context=f"stages[{index}].resource_class",
                ),
                qualification_mode=qualification_mode,
            )
        )
    if len(stages) != len({stage.id for stage in stages}):
        raise ConfigError("stage ids must be unique")
    return tuple(stages)


def _parse_profiles(value: Any) -> tuple[ProfileDefinition, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError("profiles must be a nonempty array of tables")
    profiles: list[ProfileDefinition] = []
    for index, item in enumerate(value):
        raw = _closed_mapping(
            item,
            context=f"profiles[{index}]",
            required={
                "id",
                "stage_ids",
                "authoritative",
                "admission_eligible",
                "live_eligible",
                "summary",
            },
        )
        profiles.append(
            ProfileDefinition(
                id=_string(raw["id"], context=f"profiles[{index}].id"),
                stage_ids=_string_tuple(
                    raw["stage_ids"],
                    context=f"profiles[{index}].stage_ids",
                ),
                authoritative=_boolean(
                    raw["authoritative"],
                    context=f"profiles[{index}].authoritative",
                ),
                admission_eligible=_boolean(
                    raw["admission_eligible"],
                    context=f"profiles[{index}].admission_eligible",
                ),
                live_eligible=_boolean(
                    raw["live_eligible"],
                    context=f"profiles[{index}].live_eligible",
                ),
                summary=_string(
                    raw["summary"],
                    context=f"profiles[{index}].summary",
                ),
            )
        )
    if len(profiles) != len({profile.id for profile in profiles}):
        raise ConfigError("profile ids must be unique")
    return tuple(profiles)


def _validate_semantics(config: TestGateConfig) -> None:
    if config.schema_id != CONFIG_SCHEMA_ID:
        raise ConfigError(
            f"unsupported config schema {config.schema_id!r}; expected {CONFIG_SCHEMA_ID!r}"
        )
    if config.worker_hard_max > 4:
        raise ConfigError("worker_hard_max must not exceed 4")
    if config.supported_profiles != SUPPORTED_PROFILE_IDS:
        raise ConfigError(
            f"supported_profiles must be exactly {SUPPORTED_PROFILE_IDS!r}"
        )
    if config.forbidden_dispatch_profiles != FORBIDDEN_DISPATCH_PROFILE_IDS:
        raise ConfigError(
            "forbidden_dispatch_profiles must explicitly contain only "
            "architecture_admission and live_campaign"
        )
    if tuple(profile.id for profile in config.profiles) != SUPPORTED_PROFILE_IDS:
        raise ConfigError("profiles must exactly match supported_profiles in order")
    if config.evidence_policy != EvidencePolicy(
        repository_plane_only=True,
        requires_checkout_external_output_root=True,
        product_state_writes=False,
    ):
        raise ConfigError(
            "operator evidence must remain repository-only, checkout-external, "
            "and forbidden from product-state writes"
        )
    if config.resource_policy.closed_classes != RESOURCE_CLASSES:
        raise ConfigError(f"resource classes must be exactly {RESOURCE_CLASSES!r}")
    if config.resource_policy.default_class != "serial_unknown":
        raise ConfigError("unclassified resources must default to serial_unknown")
    if not set(config.resource_policy.parallel_eligible_classes) <= {
        "parallel_pure",
        "parallel_temp_root",
    }:
        raise ConfigError("only proven pure/temp-root classes may be parallel eligible")
    if (
        config.pytest_contract.forbidden_non_live_markers
        != EXPECTED_FORBIDDEN_NON_LIVE_MARKERS
    ):
        raise ConfigError(
            "pytest forbidden markers must preserve the current non-live boundary"
        )
    if set(config.pytest_contract.allowed_non_live_markers) & set(
        config.pytest_contract.forbidden_non_live_markers
    ):
        raise ConfigError("pytest allowed and forbidden markers must be disjoint")
    if (
        config.pytest_contract.architecture_scenario_marker
        not in config.pytest_contract.allowed_non_live_markers
    ):
        raise ConfigError(
            "architecture scenario marker must be an allowed non-live marker"
        )

    environment_ids = {policy.id for policy in config.environment_policies}
    stage_ids = {stage.id for stage in config.stages}
    for stage in config.stages:
        if stage.environment_policy not in environment_ids:
            raise ConfigError(
                f"stage {stage.id!r} references unknown environment policy "
                f"{stage.environment_policy!r}"
            )
        if stage.resource_class not in RESOURCE_CLASSES:
            raise ConfigError(
                f"stage {stage.id!r} references unknown resource class "
                f"{stage.resource_class!r}"
            )
    for profile in config.profiles:
        unknown_stages = sorted(set(profile.stage_ids) - stage_ids)
        if unknown_stages:
            raise ConfigError(
                f"profile {profile.id!r} references unknown stages: "
                f"{', '.join(unknown_stages)}"
            )

    mainline = config.profile("mainline_authoritative")
    if mainline.stage_ids != LEGACY_MAINLINE_STAGE_ORDER:
        raise ConfigError(
            "mainline_authoritative stages must preserve the legacy order"
        )
    if (
        not mainline.authoritative
        or mainline.admission_eligible
        or mainline.live_eligible
    ):
        raise ConfigError(
            "mainline_authoritative proves only the non-live merge gate"
        )
    for profile_id in ("focused_diagnostic", "affected_scope_diagnostic"):
        profile = config.profile(profile_id)
        if (
            profile.authoritative
            or profile.admission_eligible
            or profile.live_eligible
        ):
            raise ConfigError(f"{profile_id} must remain permanently non-authoritative")

    qualification = config.stage("architecture_qualification_premerge")
    if qualification.qualification_mode != "premerge_subset":
        raise ConfigError("mainline qualification mode must remain premerge_subset")
    general = config.stage("general_non_live_pytest")
    if (
        len(general.argv) < 2
        or general.argv[-2:] != (
            "-m",
            config.pytest_contract.marker_expression,
        )
    ):
        raise ConfigError(
            "general pytest argv must use the versioned marker expression"
        )
    for policy in config.environment_policies:
        if policy.forbidden_markers != (
            config.pytest_contract.forbidden_non_live_markers
        ):
            raise ConfigError(
                f"environment policy {policy.id!r} marker boundary drifted"
            )


def load_config(path: Path) -> TestGateConfig:
    """Load and strictly validate one versioned test-gate configuration."""

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"cannot read test-gate config {path}: {exc}") from exc
    try:
        parsed = tomllib.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"invalid test-gate TOML {path}: {exc}") from exc

    root = _closed_mapping(
        parsed,
        context="test-gate config",
        required={
            "schema_id",
            "worker_hard_max",
            "supported_profiles",
            "forbidden_dispatch_profiles",
            "operator_evidence",
            "resource_policy",
            "pytest_contract",
            "environment_policies",
            "stages",
            "profiles",
        },
    )
    evidence_raw = _closed_mapping(
        root["operator_evidence"],
        context="operator_evidence",
        required={
            "repository_plane_only",
            "requires_checkout_external_output_root",
            "product_state_writes",
        },
    )
    resource_raw = _closed_mapping(
        root["resource_policy"],
        context="resource_policy",
        required={
            "default_class",
            "closed_classes",
            "parallel_eligible_classes",
        },
    )
    pytest_raw = _closed_mapping(
        root["pytest_contract"],
        context="pytest_contract",
        required={
            "marker_expression",
            "allowed_non_live_markers",
            "forbidden_non_live_markers",
            "architecture_scenario_marker",
        },
    )
    config = TestGateConfig(
        schema_id=_string(root["schema_id"], context="schema_id"),
        digest=sha256_digest(raw_bytes),
        worker_hard_max=_positive_int(
            root["worker_hard_max"],
            context="worker_hard_max",
        ),
        supported_profiles=_string_tuple(
            root["supported_profiles"],
            context="supported_profiles",
            allow_empty=False,
        ),
        forbidden_dispatch_profiles=_string_tuple(
            root["forbidden_dispatch_profiles"],
            context="forbidden_dispatch_profiles",
            allow_empty=False,
        ),
        evidence_policy=EvidencePolicy(
            repository_plane_only=_boolean(
                evidence_raw["repository_plane_only"],
                context="operator_evidence.repository_plane_only",
            ),
            requires_checkout_external_output_root=_boolean(
                evidence_raw["requires_checkout_external_output_root"],
                context="operator_evidence.requires_checkout_external_output_root",
            ),
            product_state_writes=_boolean(
                evidence_raw["product_state_writes"],
                context="operator_evidence.product_state_writes",
            ),
        ),
        resource_policy=ResourcePolicy(
            default_class=_string(
                resource_raw["default_class"],
                context="resource_policy.default_class",
            ),
            closed_classes=_string_tuple(
                resource_raw["closed_classes"],
                context="resource_policy.closed_classes",
                allow_empty=False,
            ),
            parallel_eligible_classes=_string_tuple(
                resource_raw["parallel_eligible_classes"],
                context="resource_policy.parallel_eligible_classes",
            ),
        ),
        pytest_contract=PytestContract(
            marker_expression=_string(
                pytest_raw["marker_expression"],
                context="pytest_contract.marker_expression",
            ),
            allowed_non_live_markers=_string_tuple(
                pytest_raw["allowed_non_live_markers"],
                context="pytest_contract.allowed_non_live_markers",
                allow_empty=False,
            ),
            forbidden_non_live_markers=_string_tuple(
                pytest_raw["forbidden_non_live_markers"],
                context="pytest_contract.forbidden_non_live_markers",
                allow_empty=False,
            ),
            architecture_scenario_marker=_string(
                pytest_raw["architecture_scenario_marker"],
                context="pytest_contract.architecture_scenario_marker",
            ),
        ),
        environment_policies=_parse_environment_policies(
            root["environment_policies"]
        ),
        stages=_parse_stages(root["stages"]),
        profiles=_parse_profiles(root["profiles"]),
    )
    _validate_semantics(config)
    return config


def validate_dispatch_profile(
    config: TestGateConfig,
    profile_id: str,
) -> ProfileDefinition:
    """Return a supported profile or reject authority domains outside this gate."""

    if profile_id in config.forbidden_dispatch_profiles:
        raise ConfigError(
            f"{profile_id!r} is outside the test-gate dispatcher; use its "
            "existing explicit operator entry point"
        )
    if profile_id not in config.supported_profiles:
        raise ConfigError(f"unsupported test-gate profile: {profile_id!r}")
    return config.profile(profile_id)
