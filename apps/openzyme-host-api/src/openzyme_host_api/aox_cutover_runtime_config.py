from __future__ import annotations

from collections.abc import Mapping
import math
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from openzyme_runtime import DEFAULT_PROVIDER_LIMITS
from openzyme_runtime import is_micu_provider_url
from openzyme_runtime import LIVE_MICU_TOKEN_HARD_LIMIT

from .aox_scientific_contract import AOX_SELECTED_CHAIN_CONTRACT_V2
from .aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST,
)
from .aox_scientific_contract import AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID
from .aox_scientific_contract import AOX_SELECTED_CHAIN_WORKFLOW_ID


AOX_BLANK_WORLD_RUNTIME_CONFIG_LEGACY_SCHEMA_ID = (
    "aox_blank_world_runtime_config@1"
)
AOX_BLANK_WORLD_RUNTIME_CONFIG_V2_SCHEMA_ID = "aox_blank_world_runtime_config@2"
AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID = "aox_blank_world_runtime_config@3"
AOX_RUNNER_CONTRACT_EXPECTATIONS_SCHEMA_ID = "aox_runner_contract_expectations@1"
AOX_BROWSER_OBSERVATION_MODE = "chrome_devtools_mcp_file_handoff"
AOX_CUTOVER_SANDBOX_EXEC_TIMEOUT_SECONDS = 3_600
AOX_CUTOVER_MIN_ATTEMPT_TIMEOUT_SECONDS = 2.0 * AOX_CUTOVER_SANDBOX_EXEC_TIMEOUT_SECONDS
AOX_CUTOVER_DEFAULT_ATTEMPT_TIMEOUT_SECONDS = AOX_CUTOVER_MIN_ATTEMPT_TIMEOUT_SECONDS
AOX_CUTOVER_MAX_SIGNALS_PER_DRAIN = 1
AOX_DURABLE_ROUTE_POLICY_IDS = frozenset(
    {
        "bio.ncbi_fetch_proteins.provider:v1",
        "bio.uniprot_fetch.provider:v1",
        "bio.hmmer_search.provider:v1",
        "bio_tools.mafft.hpc:v1",
        "bio_tools.hmmbuild.hpc:v1",
        "bio_tools.cdhit.hpc:v1",
        "bio_tools.hmmalign.hpc:v1",
    }
)

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PURPOSE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")

_LEGACY_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_id",
        "host",
        "execution",
        "limits",
        "llm",
        "research",
        "tracing",
        "test_opt_in",
        "driver",
    }
)
_V2_TOP_LEVEL_FIELDS = _LEGACY_TOP_LEVEL_FIELDS | {"reliability"}
_TOP_LEVEL_FIELDS = _V2_TOP_LEVEL_FIELDS | {"scientific_workflow_contract"}
_HOST_FIELDS = frozenset(
    {
        "deployment_profile",
        "storage_profile",
        "background_runtime_enabled",
        "debug_enabled",
        "principal_count",
    }
)
_EXECUTION_FIELDS = frozenset(
    {
        "backend",
        "hpc_runner_config_digest",
        "aox_runner_contract_expectations",
    }
)
_RUNNER_EXPECTATION_FIELDS = frozenset({"schema_id", "manifest_digest", "contracts"})
_RUNNER_CONTRACT_FIELDS = frozenset(
    {"adapter_id", "command_template_id", "runner_contract_digest"}
)
_LLM_FIELDS = frozenset(
    {
        "enabled",
        "model",
        "base_url_endpoint",
        "extra_body_digest",
        "default_headers_digest",
        "use_responses_api",
        "max_tokens",
        "timeout",
        "max_retries",
        "temperature",
        "structured_output_method",
        "structured_output_retry_backoff_seconds",
        "purpose_policies",
        "context_window_tokens",
        "default_output_tokens",
        "context_warn_ratio",
        "context_auto_compact_ratio",
        "context_emergency_ratio",
        "tokenizer_enabled",
    }
)
_PURPOSE_POLICY_FIELDS = frozenset(
    {
        "max_tokens",
        "timeout",
        "max_retries",
        "structured_output_method",
        "structured_output_retry_backoff_seconds",
    }
)
_RESEARCH_FIELDS = frozenset(
    {
        "max_units",
        "allow_clarification",
        "max_research_iterations",
        "max_react_tool_calls",
        "max_concurrent_research_units",
        "tavily_max_results",
        "tavily_topic",
        "tavily_timeout_seconds",
        "mcp_enabled",
        "mcp_tool_allowlist",
        "provider_timeout_seconds",
        "provider_max_attempts",
        "credential_slots",
        "ncbi_identity_digest",
    }
)
_CREDENTIAL_SLOT_FIELDS = frozenset({"llm", "ncbi", "semantic_scholar", "tavily"})
_TRACING_FIELDS = frozenset({"enabled", "project_name_digest"})
_TEST_OPT_IN_FIELDS = frozenset(
    {
        "live_llm",
        "live_tavily",
        "live_hpc",
        "live_e2e",
        "quality_eval",
        "upload_langsmith",
    }
)
_RELIABILITY_FIELDS = frozenset(
    {
        "shadow_observability",
        "controlled_operation_owner_policy",
        "durable_execution_route_allowlist",
        "runtime_drain_contract",
        "mutation_closure_mode",
        "shadow_max_observations",
    }
)
_SCIENTIFIC_WORKFLOW_CONTRACT_FIELDS = frozenset(
    {
        "schema_id",
        "contract_id",
        "workflow_id",
        "workflow_contract_digest",
    }
)
_DRIVER_FIELDS = frozenset(
    {
        "scenario",
        "approval_mode",
        "browser_observation_mode",
        "timeout_seconds",
        "max_drains",
        "max_signals_per_drain",
        "max_steps_per_agent",
        "browser_poll_interval_seconds",
        "browser_approval_timeout_seconds",
        "browser_completion_hold_seconds",
        "browser_observation_submission_timeout_seconds",
        "ui_dist_digest",
        "micu_hard_limit_tokens",
        "micu_ledger_identity_digest",
    }
)


class AoxRuntimeConfigSchemaError(ValueError):
    def __init__(
        self,
        path: str,
        message: str,
        *,
        missing: set[str] | frozenset[str] = frozenset(),
        unexpected: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        self.path = path
        self.missing = tuple(sorted(missing))
        self.unexpected = tuple(sorted(unexpected))
        super().__init__(f"{path}: {message}")

    def details(self) -> dict[str, object]:
        details: dict[str, object] = {"identity": self.path}
        if self.missing:
            details["missing"] = list(self.missing)
        if self.unexpected:
            details["unexpected"] = list(self.unexpected)
        return details


def _closed_object(
    value: object,
    *,
    fields: frozenset[str],
    path: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AoxRuntimeConfigSchemaError(path, "must be an object")
    record = dict(value)
    if any(not isinstance(key, str) for key in record):
        raise AoxRuntimeConfigSchemaError(path, "must use string field names")
    actual = set(record)
    if actual != fields:
        raise AoxRuntimeConfigSchemaError(
            path,
            "must match the exact closed field set",
            missing=fields - actual,
            unexpected=actual - fields,
        )
    return record


def _boolean(value: object, *, path: str) -> bool:
    if type(value) is not bool:
        raise AoxRuntimeConfigSchemaError(path, "must be a boolean")
    return value


def _integer(
    value: object,
    *,
    path: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        raise AoxRuntimeConfigSchemaError(path, "must be an integer")
    if minimum is not None and value < minimum:
        raise AoxRuntimeConfigSchemaError(path, f"must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise AoxRuntimeConfigSchemaError(path, f"must be at most {maximum}")
    return value


def _optional_integer(
    value: object,
    *,
    path: str,
    minimum: int,
    maximum: int | None = None,
) -> int | None:
    if value is None:
        return None
    return _integer(value, path=path, minimum=minimum, maximum=maximum)


def _number(
    value: object,
    *,
    path: str,
    minimum: float | None = None,
    maximum: float | None = None,
    minimum_inclusive: bool = True,
) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise AoxRuntimeConfigSchemaError(path, "must be a finite number")
    normalized = float(value)
    if normalized == 0.0:
        normalized = 0.0
    if minimum is not None and (
        normalized < minimum if minimum_inclusive else normalized <= minimum
    ):
        qualifier = "at least" if minimum_inclusive else "greater than"
        raise AoxRuntimeConfigSchemaError(path, f"must be {qualifier} {minimum}")
    if maximum is not None and normalized > maximum:
        raise AoxRuntimeConfigSchemaError(path, f"must be at most {maximum}")
    return normalized


def _optional_number(
    value: object,
    *,
    path: str,
    minimum: float,
    minimum_inclusive: bool,
) -> float | None:
    if value is None:
        return None
    return _number(
        value,
        path=path,
        minimum=minimum,
        minimum_inclusive=minimum_inclusive,
    )


def _string(
    value: object,
    *,
    path: str,
    allowed: frozenset[str] | None = None,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise AoxRuntimeConfigSchemaError(path, "must be a canonical non-empty string")
    if allowed is not None and value not in allowed:
        raise AoxRuntimeConfigSchemaError(path, "uses an unsupported value")
    return value


def _optional_string(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    return _string(value, path=path)


def _digest(value: object, *, path: str) -> str:
    digest = _string(value, path=path)
    if _DIGEST_PATTERN.fullmatch(digest) is None:
        raise AoxRuntimeConfigSchemaError(path, "must be a canonical SHA-256 digest")
    return digest


def _optional_digest(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    return _digest(value, path=path)


def _string_list(value: object, *, path: str) -> list[str]:
    if type(value) is not list:
        raise AoxRuntimeConfigSchemaError(path, "must be an array")
    normalized = [
        _string(item, path=f"{path}[{index}]") for index, item in enumerate(value)
    ]
    if len(normalized) != len(set(normalized)):
        raise AoxRuntimeConfigSchemaError(path, "must not contain duplicates")
    return normalized


def _micu_endpoint(value: object, *, path: str) -> str:
    endpoint = _string(value, path=path)
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise AoxRuntimeConfigSchemaError(
            path, "must be a valid MICU endpoint"
        ) from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not is_micu_provider_url(endpoint)
    ):
        raise AoxRuntimeConfigSchemaError(
            path, "must be a credential-free MICU HTTP(S) endpoint"
        )
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    normalized = urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path.rstrip("/"), "", "")
    )
    if endpoint != normalized:
        raise AoxRuntimeConfigSchemaError(path, "must use canonical endpoint syntax")
    return endpoint


def _normalize_runner_expectations(
    value: object,
    *,
    expected_runner_contracts: Mapping[str, Mapping[str, str]],
    path: str,
) -> dict[str, object]:
    expectations = _closed_object(
        value,
        fields=_RUNNER_EXPECTATION_FIELDS,
        path=path,
    )
    expected_by_tool_id = {
        str(contract["tool_id"]): contract
        for contract in expected_runner_contracts.values()
    }
    contracts_path = f"{path}.contracts"
    contracts = _closed_object(
        expectations["contracts"],
        fields=frozenset(expected_by_tool_id),
        path=contracts_path,
    )
    normalized_contracts: dict[str, dict[str, str]] = {}
    for tool_id in sorted(expected_by_tool_id):
        contract_path = f"{contracts_path}.{tool_id}"
        record = _closed_object(
            contracts[tool_id],
            fields=_RUNNER_CONTRACT_FIELDS,
            path=contract_path,
        )
        expected = expected_by_tool_id[tool_id]
        adapter_id = _string(record["adapter_id"], path=f"{contract_path}.adapter_id")
        template_id = _string(
            record["command_template_id"],
            path=f"{contract_path}.command_template_id",
        )
        if (
            adapter_id != expected["adapter_id"]
            or template_id != expected["command_template_id"]
        ):
            raise AoxRuntimeConfigSchemaError(
                contract_path,
                "does not match the canonical AOX adapter/template identity",
            )
        normalized_contracts[tool_id] = {
            "adapter_id": adapter_id,
            "command_template_id": template_id,
            "runner_contract_digest": _digest(
                record["runner_contract_digest"],
                path=f"{contract_path}.runner_contract_digest",
            ),
        }
    schema_id = _string(expectations["schema_id"], path=f"{path}.schema_id")
    if schema_id != AOX_RUNNER_CONTRACT_EXPECTATIONS_SCHEMA_ID:
        raise AoxRuntimeConfigSchemaError(
            f"{path}.schema_id", "uses an unsupported runner expectation schema"
        )
    return {
        "schema_id": schema_id,
        "manifest_digest": _digest(
            expectations["manifest_digest"], path=f"{path}.manifest_digest"
        ),
        "contracts": normalized_contracts,
    }


def _normalize_purpose_policies(value: object, *, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AoxRuntimeConfigSchemaError(path, "must be an object")
    policies = dict(value)
    if any(not isinstance(purpose, str) for purpose in policies):
        raise AoxRuntimeConfigSchemaError(path, "must use string purpose identifiers")
    normalized: dict[str, object] = {}
    for purpose in sorted(policies):
        if _PURPOSE_PATTERN.fullmatch(purpose) is None:
            raise AoxRuntimeConfigSchemaError(
                path, "contains a malformed purpose identifier"
            )
        policy_path = f"{path}.{purpose}"
        policy = _closed_object(
            policies[purpose],
            fields=_PURPOSE_POLICY_FIELDS,
            path=policy_path,
        )
        normalized[purpose] = {
            "max_tokens": _optional_integer(
                policy["max_tokens"],
                path=f"{policy_path}.max_tokens",
                minimum=1,
                maximum=LIVE_MICU_TOKEN_HARD_LIMIT,
            ),
            "timeout": _optional_number(
                policy["timeout"],
                path=f"{policy_path}.timeout",
                minimum=0.0,
                minimum_inclusive=False,
            ),
            "max_retries": (
                None
                if policy["max_retries"] is None
                else _integer(
                    policy["max_retries"],
                    path=f"{policy_path}.max_retries",
                    minimum=0,
                )
            ),
            "structured_output_method": _optional_string(
                policy["structured_output_method"],
                path=f"{policy_path}.structured_output_method",
            ),
            "structured_output_retry_backoff_seconds": _optional_number(
                policy["structured_output_retry_backoff_seconds"],
                path=f"{policy_path}.structured_output_retry_backoff_seconds",
                minimum=0.0,
                minimum_inclusive=True,
            ),
        }
    return normalized


def normalize_aox_blank_world_runtime_config(
    value: Mapping[str, object],
    *,
    expected_runner_contracts: Mapping[str, Mapping[str, str]],
) -> dict[str, object]:
    """Validate and canonicalize a sealed AOX runtime configuration.

    Numeric duration/ratio fields are normalized to finite JSON floats. All objects
    use exact field allowlists; no caller-provided field is silently discarded.
    Historical ``@1`` and ``@2`` remain readable solely so frozen evidence can
    be reverified. New launch configuration is always emitted as ``@3`` and
    additionally binds the complete active selected-chain ``@2`` contract
    identity into the launch config digest before any attempt root is created.
    """

    if not isinstance(value, Mapping):
        raise AoxRuntimeConfigSchemaError("effective_config", "must be an object")
    raw_schema_id = value.get("schema_id")
    if raw_schema_id == AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID:
        top_level_fields = _TOP_LEVEL_FIELDS
    elif raw_schema_id == AOX_BLANK_WORLD_RUNTIME_CONFIG_V2_SCHEMA_ID:
        top_level_fields = _V2_TOP_LEVEL_FIELDS
    elif raw_schema_id == AOX_BLANK_WORLD_RUNTIME_CONFIG_LEGACY_SCHEMA_ID:
        top_level_fields = _LEGACY_TOP_LEVEL_FIELDS
    else:
        raise AoxRuntimeConfigSchemaError(
            "effective_config.schema_id", "uses an unsupported runtime config schema"
        )
    root = _closed_object(
        value,
        fields=top_level_fields,
        path="effective_config",
    )
    schema_id = _string(root["schema_id"], path="effective_config.schema_id")

    host = _closed_object(
        root["host"], fields=_HOST_FIELDS, path="effective_config.host"
    )
    deployment_profile = _string(
        host["deployment_profile"], path="effective_config.host.deployment_profile"
    )
    storage_profile = _string(
        host["storage_profile"], path="effective_config.host.storage_profile"
    )
    if deployment_profile != "local-dev" or storage_profile != "single_process_sqlite":
        raise AoxRuntimeConfigSchemaError(
            "effective_config.host",
            "must bind the trusted local-dev single-process SQLite profile",
        )
    if host["background_runtime_enabled"] is not False or host["principal_count"] != 0:
        raise AoxRuntimeConfigSchemaError(
            "effective_config.host",
            "must disable background runtime and shared principals",
        )
    normalized_host = {
        "deployment_profile": deployment_profile,
        "storage_profile": storage_profile,
        "background_runtime_enabled": _boolean(
            host["background_runtime_enabled"],
            path="effective_config.host.background_runtime_enabled",
        ),
        "debug_enabled": _boolean(
            host["debug_enabled"], path="effective_config.host.debug_enabled"
        ),
        "principal_count": _integer(
            host["principal_count"],
            path="effective_config.host.principal_count",
            minimum=0,
            maximum=0,
        ),
    }

    execution = _closed_object(
        root["execution"], fields=_EXECUTION_FIELDS, path="effective_config.execution"
    )
    backend = _string(execution["backend"], path="effective_config.execution.backend")
    if backend != "hpc":
        raise AoxRuntimeConfigSchemaError(
            "effective_config.execution.backend", "must be hpc"
        )
    normalized_execution = {
        "backend": backend,
        "hpc_runner_config_digest": _digest(
            execution["hpc_runner_config_digest"],
            path="effective_config.execution.hpc_runner_config_digest",
        ),
        "aox_runner_contract_expectations": _normalize_runner_expectations(
            execution["aox_runner_contract_expectations"],
            expected_runner_contracts=expected_runner_contracts,
            path="effective_config.execution.aox_runner_contract_expectations",
        ),
    }

    limits = _closed_object(
        root["limits"],
        fields=frozenset(DEFAULT_PROVIDER_LIMITS),
        path="effective_config.limits",
    )
    normalized_limits = {
        key: _integer(limits[key], path=f"effective_config.limits.{key}", minimum=1)
        for key in sorted(DEFAULT_PROVIDER_LIMITS)
    }

    llm = _closed_object(root["llm"], fields=_LLM_FIELDS, path="effective_config.llm")
    if llm["enabled"] is not True:
        raise AoxRuntimeConfigSchemaError(
            "effective_config.llm.enabled", "must be true"
        )
    max_tokens = _optional_integer(
        llm["max_tokens"],
        path="effective_config.llm.max_tokens",
        minimum=1,
        maximum=LIVE_MICU_TOKEN_HARD_LIMIT,
    )
    context_window = _optional_integer(
        llm["context_window_tokens"],
        path="effective_config.llm.context_window_tokens",
        minimum=1,
    )
    if context_window is None:
        raise AoxRuntimeConfigSchemaError(
            "effective_config.llm.context_window_tokens",
            "must be an explicit conservative provider override for blank-world live cutover",
        )
    if context_window > 200_000:
        raise AoxRuntimeConfigSchemaError(
            "effective_config.llm.context_window_tokens",
            "must not exceed the 200000-token conservative blank-world live ceiling",
        )
    default_output = _optional_integer(
        llm["default_output_tokens"],
        path="effective_config.llm.default_output_tokens",
        minimum=1,
        maximum=LIVE_MICU_TOKEN_HARD_LIMIT,
    )
    if (
        context_window is not None
        and default_output is not None
        and default_output > context_window
    ):
        raise AoxRuntimeConfigSchemaError(
            "effective_config.llm.default_output_tokens",
            "must not exceed context_window_tokens",
        )
    warn_ratio = _number(
        llm["context_warn_ratio"],
        path="effective_config.llm.context_warn_ratio",
        minimum=0.0,
        maximum=1.0,
        minimum_inclusive=False,
    )
    compact_ratio = _number(
        llm["context_auto_compact_ratio"],
        path="effective_config.llm.context_auto_compact_ratio",
        minimum=0.0,
        maximum=1.0,
        minimum_inclusive=False,
    )
    emergency_ratio = _number(
        llm["context_emergency_ratio"],
        path="effective_config.llm.context_emergency_ratio",
        minimum=0.0,
        maximum=1.0,
        minimum_inclusive=False,
    )
    if not warn_ratio < compact_ratio < emergency_ratio:
        raise AoxRuntimeConfigSchemaError(
            "effective_config.llm",
            "context ratios must increase from warn to compact to emergency",
        )
    normalized_llm = {
        "enabled": _boolean(llm["enabled"], path="effective_config.llm.enabled"),
        "model": _string(llm["model"], path="effective_config.llm.model"),
        "base_url_endpoint": _micu_endpoint(
            llm["base_url_endpoint"], path="effective_config.llm.base_url_endpoint"
        ),
        "extra_body_digest": _digest(
            llm["extra_body_digest"], path="effective_config.llm.extra_body_digest"
        ),
        "default_headers_digest": _digest(
            llm["default_headers_digest"],
            path="effective_config.llm.default_headers_digest",
        ),
        "use_responses_api": _boolean(
            llm["use_responses_api"], path="effective_config.llm.use_responses_api"
        ),
        "max_tokens": max_tokens,
        "timeout": _optional_number(
            llm["timeout"],
            path="effective_config.llm.timeout",
            minimum=0.0,
            minimum_inclusive=False,
        ),
        "max_retries": _integer(
            llm["max_retries"], path="effective_config.llm.max_retries", minimum=0
        ),
        "temperature": _number(
            llm["temperature"],
            path="effective_config.llm.temperature",
            minimum=0.0,
        ),
        "structured_output_method": _string(
            llm["structured_output_method"],
            path="effective_config.llm.structured_output_method",
        ),
        "structured_output_retry_backoff_seconds": _number(
            llm["structured_output_retry_backoff_seconds"],
            path="effective_config.llm.structured_output_retry_backoff_seconds",
            minimum=0.0,
        ),
        "purpose_policies": _normalize_purpose_policies(
            llm["purpose_policies"], path="effective_config.llm.purpose_policies"
        ),
        "context_window_tokens": context_window,
        "default_output_tokens": default_output,
        "context_warn_ratio": warn_ratio,
        "context_auto_compact_ratio": compact_ratio,
        "context_emergency_ratio": emergency_ratio,
        "tokenizer_enabled": _boolean(
            llm["tokenizer_enabled"], path="effective_config.llm.tokenizer_enabled"
        ),
    }

    research = _closed_object(
        root["research"], fields=_RESEARCH_FIELDS, path="effective_config.research"
    )
    slots = _closed_object(
        research["credential_slots"],
        fields=_CREDENTIAL_SLOT_FIELDS,
        path="effective_config.research.credential_slots",
    )
    normalized_slots = {
        key: _boolean(
            slots[key], path=f"effective_config.research.credential_slots.{key}"
        )
        for key in sorted(_CREDENTIAL_SLOT_FIELDS)
    }
    if not normalized_slots["llm"] or not normalized_slots["ncbi"]:
        raise AoxRuntimeConfigSchemaError(
            "effective_config.research.credential_slots",
            "must mark LLM and NCBI credentials ready",
        )
    normalized_research = {
        "max_units": _integer(
            research["max_units"],
            path="effective_config.research.max_units",
            minimum=1,
        ),
        "allow_clarification": _boolean(
            research["allow_clarification"],
            path="effective_config.research.allow_clarification",
        ),
        "max_research_iterations": _integer(
            research["max_research_iterations"],
            path="effective_config.research.max_research_iterations",
            minimum=1,
        ),
        "max_react_tool_calls": _integer(
            research["max_react_tool_calls"],
            path="effective_config.research.max_react_tool_calls",
            minimum=1,
        ),
        "max_concurrent_research_units": _integer(
            research["max_concurrent_research_units"],
            path="effective_config.research.max_concurrent_research_units",
            minimum=1,
        ),
        "tavily_max_results": _integer(
            research["tavily_max_results"],
            path="effective_config.research.tavily_max_results",
            minimum=1,
        ),
        "tavily_topic": _string(
            research["tavily_topic"], path="effective_config.research.tavily_topic"
        ),
        "tavily_timeout_seconds": _number(
            research["tavily_timeout_seconds"],
            path="effective_config.research.tavily_timeout_seconds",
            minimum=0.0,
            minimum_inclusive=False,
        ),
        "mcp_enabled": _boolean(
            research["mcp_enabled"], path="effective_config.research.mcp_enabled"
        ),
        "mcp_tool_allowlist": _string_list(
            research["mcp_tool_allowlist"],
            path="effective_config.research.mcp_tool_allowlist",
        ),
        "provider_timeout_seconds": _number(
            research["provider_timeout_seconds"],
            path="effective_config.research.provider_timeout_seconds",
            minimum=0.0,
            minimum_inclusive=False,
        ),
        "provider_max_attempts": _integer(
            research["provider_max_attempts"],
            path="effective_config.research.provider_max_attempts",
            minimum=1,
        ),
        "credential_slots": normalized_slots,
        "ncbi_identity_digest": _digest(
            research["ncbi_identity_digest"],
            path="effective_config.research.ncbi_identity_digest",
        ),
    }
    if normalized_research["mcp_enabled"] is not True:
        raise AoxRuntimeConfigSchemaError(
            "effective_config.research.mcp_enabled", "must be true"
        )

    tracing = _closed_object(
        root["tracing"], fields=_TRACING_FIELDS, path="effective_config.tracing"
    )
    normalized_tracing = {
        "enabled": _boolean(
            tracing["enabled"], path="effective_config.tracing.enabled"
        ),
        "project_name_digest": _digest(
            tracing["project_name_digest"],
            path="effective_config.tracing.project_name_digest",
        ),
    }

    test_opt_in = _closed_object(
        root["test_opt_in"],
        fields=_TEST_OPT_IN_FIELDS,
        path="effective_config.test_opt_in",
    )
    normalized_test = {
        key: _boolean(test_opt_in[key], path=f"effective_config.test_opt_in.{key}")
        for key in sorted(_TEST_OPT_IN_FIELDS)
    }
    if not all(normalized_test[key] for key in ("live_llm", "live_hpc", "live_e2e")):
        raise AoxRuntimeConfigSchemaError(
            "effective_config.test_opt_in",
            "must explicitly enable live_llm, live_hpc, and live_e2e",
        )

    normalized_reliability: dict[str, object] | None = None
    if schema_id in {
        AOX_BLANK_WORLD_RUNTIME_CONFIG_V2_SCHEMA_ID,
        AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID,
    }:
        reliability = _closed_object(
            root["reliability"],
            fields=_RELIABILITY_FIELDS,
            path="effective_config.reliability",
        )
        owner_policy = _string(
            reliability["controlled_operation_owner_policy"],
            path=(
                "effective_config.reliability."
                "controlled_operation_owner_policy"
            ),
            allowed=frozenset({"route_allowlist_v1", "durable_only_v1"}),
        )
        durable_routes = _string_list(
            reliability["durable_execution_route_allowlist"],
            path=(
                "effective_config.reliability."
                "durable_execution_route_allowlist"
            ),
        )
        if durable_routes != sorted(durable_routes):
            raise AoxRuntimeConfigSchemaError(
                "effective_config.reliability.durable_execution_route_allowlist",
                "must be sorted",
            )
        missing_routes = sorted(AOX_DURABLE_ROUTE_POLICY_IDS - set(durable_routes))
        if owner_policy != "durable_only_v1" and missing_routes:
            raise AoxRuntimeConfigSchemaError(
                "effective_config.reliability.durable_execution_route_allowlist",
                "must include every AOX provider and HPC route",
            )
        runtime_drain_contract = _string(
            reliability["runtime_drain_contract"],
            path="effective_config.reliability.runtime_drain_contract",
            allowed=frozenset({"command_v1"}),
        )
        mutation_closure_mode = _string(
            reliability["mutation_closure_mode"],
            path="effective_config.reliability.mutation_closure_mode",
            allowed=frozenset({"generic_v1"}),
        )
        normalized_reliability = {
            "shadow_observability": _string(
                reliability["shadow_observability"],
                path="effective_config.reliability.shadow_observability",
                allowed=frozenset({"disabled", "shadow_v1"}),
            ),
            "controlled_operation_owner_policy": owner_policy,
            "durable_execution_route_allowlist": durable_routes,
            "runtime_drain_contract": runtime_drain_contract,
            "mutation_closure_mode": mutation_closure_mode,
            "shadow_max_observations": _integer(
                reliability["shadow_max_observations"],
                path="effective_config.reliability.shadow_max_observations",
                minimum=1,
                maximum=4_096,
            ),
        }

    normalized_scientific_workflow_contract: dict[str, str] | None = None
    if schema_id == AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID:
        scientific_workflow_contract = _closed_object(
            root["scientific_workflow_contract"],
            fields=_SCIENTIFIC_WORKFLOW_CONTRACT_FIELDS,
            path="effective_config.scientific_workflow_contract",
        )
        normalized_scientific_workflow_contract = {
            "schema_id": _string(
                scientific_workflow_contract["schema_id"],
                path="effective_config.scientific_workflow_contract.schema_id",
            ),
            "contract_id": _string(
                scientific_workflow_contract["contract_id"],
                path="effective_config.scientific_workflow_contract.contract_id",
            ),
            "workflow_id": _string(
                scientific_workflow_contract["workflow_id"],
                path="effective_config.scientific_workflow_contract.workflow_id",
            ),
            "workflow_contract_digest": _digest(
                scientific_workflow_contract["workflow_contract_digest"],
                path=(
                    "effective_config.scientific_workflow_contract."
                    "workflow_contract_digest"
                ),
            ),
        }
        expected_scientific_workflow_contract = {
            "schema_id": AOX_SELECTED_CHAIN_CONTRACT_V2.schema_id,
            "contract_id": AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID,
            "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
            "workflow_contract_digest": (
                AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
            ),
        }
        mismatched_contract_fields = sorted(
            key
            for key, expected in expected_scientific_workflow_contract.items()
            if normalized_scientific_workflow_contract[key] != expected
        )
        if mismatched_contract_fields:
            raise AoxRuntimeConfigSchemaError(
                "effective_config.scientific_workflow_contract",
                "must bind the exact active AOX selected-chain contract identity",
                unexpected=frozenset(mismatched_contract_fields),
            )

    driver = _closed_object(
        root["driver"], fields=_DRIVER_FIELDS, path="effective_config.driver"
    )
    scenario = _string(driver["scenario"], path="effective_config.driver.scenario")
    if scenario != "aox_blank_world_cutover":
        raise AoxRuntimeConfigSchemaError(
            "effective_config.driver.scenario", "uses an unsupported scenario"
        )
    approval_mode = _string(
        driver["approval_mode"],
        path="effective_config.driver.approval_mode",
        allowed=frozenset({"auto", "chrome-once"}),
    )
    observation_mode = _string(
        driver["browser_observation_mode"],
        path="effective_config.driver.browser_observation_mode",
    )
    if observation_mode != AOX_BROWSER_OBSERVATION_MODE:
        raise AoxRuntimeConfigSchemaError(
            "effective_config.driver.browser_observation_mode",
            "uses an unsupported browser observation channel",
        )
    ui_dist_digest = _optional_digest(
        driver["ui_dist_digest"], path="effective_config.driver.ui_dist_digest"
    )
    if (approval_mode == "chrome-once") != (ui_dist_digest is not None):
        raise AoxRuntimeConfigSchemaError(
            "effective_config.driver.ui_dist_digest",
            "must be present only for chrome-once approval",
        )
    hard_limit = _integer(
        driver["micu_hard_limit_tokens"],
        path="effective_config.driver.micu_hard_limit_tokens",
        minimum=LIVE_MICU_TOKEN_HARD_LIMIT,
        maximum=LIVE_MICU_TOKEN_HARD_LIMIT,
    )
    normalized_driver = {
        "scenario": scenario,
        "approval_mode": approval_mode,
        "browser_observation_mode": observation_mode,
        "timeout_seconds": _number(
            driver["timeout_seconds"],
            path="effective_config.driver.timeout_seconds",
            minimum=AOX_CUTOVER_MIN_ATTEMPT_TIMEOUT_SECONDS,
        ),
        "max_drains": _integer(
            driver["max_drains"],
            path="effective_config.driver.max_drains",
            minimum=1,
        ),
        "max_signals_per_drain": _integer(
            driver["max_signals_per_drain"],
            path="effective_config.driver.max_signals_per_drain",
            minimum=1,
            maximum=AOX_CUTOVER_MAX_SIGNALS_PER_DRAIN,
        ),
        "max_steps_per_agent": _integer(
            driver["max_steps_per_agent"],
            path="effective_config.driver.max_steps_per_agent",
            minimum=1,
        ),
        "browser_poll_interval_seconds": _number(
            driver["browser_poll_interval_seconds"],
            path="effective_config.driver.browser_poll_interval_seconds",
            minimum=0.0,
            minimum_inclusive=False,
        ),
        "browser_approval_timeout_seconds": _number(
            driver["browser_approval_timeout_seconds"],
            path="effective_config.driver.browser_approval_timeout_seconds",
            minimum=0.0,
            minimum_inclusive=False,
        ),
        "browser_completion_hold_seconds": _number(
            driver["browser_completion_hold_seconds"],
            path="effective_config.driver.browser_completion_hold_seconds",
            minimum=0.0,
        ),
        "browser_observation_submission_timeout_seconds": _number(
            driver["browser_observation_submission_timeout_seconds"],
            path=(
                "effective_config.driver."
                "browser_observation_submission_timeout_seconds"
            ),
            minimum=0.0,
            minimum_inclusive=False,
        ),
        "ui_dist_digest": ui_dist_digest,
        "micu_hard_limit_tokens": hard_limit,
        "micu_ledger_identity_digest": _digest(
            driver["micu_ledger_identity_digest"],
            path="effective_config.driver.micu_ledger_identity_digest",
        ),
    }

    normalized = {
        "schema_id": schema_id,
        "host": normalized_host,
        "execution": normalized_execution,
        "limits": normalized_limits,
        "llm": normalized_llm,
        "research": normalized_research,
        "tracing": normalized_tracing,
        "test_opt_in": normalized_test,
        "driver": normalized_driver,
    }
    if normalized_reliability is not None:
        normalized["reliability"] = normalized_reliability
    if normalized_scientific_workflow_contract is not None:
        normalized["scientific_workflow_contract"] = (
            normalized_scientific_workflow_contract
        )
    return normalized


__all__ = [
    "AOX_BLANK_WORLD_RUNTIME_CONFIG_LEGACY_SCHEMA_ID",
    "AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID",
    "AOX_BLANK_WORLD_RUNTIME_CONFIG_V2_SCHEMA_ID",
    "AOX_BROWSER_OBSERVATION_MODE",
    "AOX_DURABLE_ROUTE_POLICY_IDS",
    "AoxRuntimeConfigSchemaError",
    "normalize_aox_blank_world_runtime_config",
]
