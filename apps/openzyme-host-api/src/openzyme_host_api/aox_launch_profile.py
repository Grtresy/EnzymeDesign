from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from openzyme_runtime.reliability import ControlledOperationOwnerPolicy
from openzyme_runtime.reliability import MutationClosureMode
from openzyme_runtime.reliability import ReliabilityRefactorSettings
from openzyme_runtime.reliability import RuntimeDrainContract
from openzyme_runtime.reliability import ShadowObservabilityMode
from openzyme_runtime.settings import ExecutionSettings
from openzyme_runtime.settings import HostApiSettings
from openzyme_runtime.settings import HostCliSettings
from openzyme_runtime.settings import LimiterSettings
from openzyme_runtime.settings import LiveLlmTestSettings
from openzyme_runtime.settings import LlmPurposePolicy
from openzyme_runtime.settings import LlmSettings
from openzyme_runtime.settings import OpenZymeSettings
from openzyme_runtime.settings import ResearchSettings
from openzyme_runtime.settings import TestSettings
from openzyme_runtime.settings import TracingSettings
from openzyme_runtime.settings import V3BackgroundRuntimeSettings
from openzyme_runtime.settings import load_env_files

from .aox_cutover_evidence import canonical_digest
from .aox_launch_failure import AoxCutoverLaunchError


AOX_CUTOVER_LAUNCH_PROFILE_SCHEMA_ID = "aox_cutover_launch_profile@1"
AOX_CUTOVER_LAUNCH_PROFILE_FILENAME = "aox-launch-profile.json"

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SAFE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}")
_PROFILE_FIELDS = {
    "schema_id",
    "source_commit",
    "config_digest",
    "ledger_path",
    "settings",
    "created_at",
    "profile_digest",
}
_SETTINGS_FIELDS = {
    "llm",
    "research",
    "tracing",
    "host_cli",
    "host_api",
    "v3_background_runtime",
    "execution",
    "limits",
    "test",
    "reliability",
}
_LLM_FIELDS = {
    "model",
    "base_url",
    "extra_body_digest",
    "user_agent",
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
_PURPOSE_POLICY_FIELDS = {
    "max_tokens",
    "timeout",
    "max_retries",
    "structured_output_method",
    "structured_output_retry_backoff_seconds",
}
_RESEARCH_FIELDS = {
    "max_units",
    "allow_clarification",
    "max_research_iterations",
    "max_react_tool_calls",
    "max_concurrent_research_units",
    "tavily_max_results",
    "tavily_topic",
    "mcp_tool_allowlist",
    "tavily_timeout_seconds",
    "pubmed_tool",
    "provider_timeout_seconds",
    "provider_max_attempts",
}
_TRACING_FIELDS = {"enabled", "project_name"}
_HOST_CLI_FIELDS = {"base_url", "project_id", "output_format"}
_HOST_API_FIELDS = {
    "bind_host",
    "bind_port",
    "deployment_profile",
    "debug_enabled",
}
_BACKGROUND_FIELDS = {
    "enabled",
    "poll_interval_seconds",
    "max_signals_per_tick",
    "max_steps_per_agent",
    "shutdown_timeout_seconds",
}
_EXECUTION_FIELDS = {"backend", "hpc_runner_config"}
_LIMITS_FIELDS = {"provider_limits"}
_TEST_FIELDS = {
    "enable_live_llm",
    "enable_live_tavily",
    "enable_live_hpc",
    "enable_live_e2e",
    "enable_quality_eval",
    "upload_langsmith",
    "live_llm",
}
_LIVE_LLM_FIELDS = {
    "max_tokens",
    "timeout",
    "max_retries",
    "structured_output_method",
    "structured_output_retry_backoff_seconds",
}
_RELIABILITY_FIELDS = {
    "shadow_observability",
    "controlled_operation_owner_policy",
    "durable_execution_route_allowlist",
    "runtime_drain_contract",
    "mutation_closure_mode",
    "shadow_max_observations",
}


def _reject(code: str, message: str, *, identity: str) -> None:
    raise AoxCutoverLaunchError(
        code,
        message,
        details={"identity": identity},
        public_cause={"kind": "schema_field", "identity": identity},
    )


def _closed_mapping(
    value: object,
    fields: set[str],
    *,
    identity: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile is not the current closed schema",
            identity=identity,
        )
    return dict(value)


def _require_string(value: object, *, identity: str, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not value:
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile contains an invalid string",
            identity=identity,
        )


def _require_bool(value: object, *, identity: str) -> None:
    if type(value) is not bool:
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile contains an invalid boolean",
            identity=identity,
        )


def _require_int(
    value: object,
    *,
    identity: str,
    optional: bool = False,
) -> None:
    if optional and value is None:
        return
    if type(value) is not int:
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile contains an invalid integer",
            identity=identity,
        )


def _require_number(
    value: object,
    *,
    identity: str,
    optional: bool = False,
) -> None:
    if optional and value is None:
        return
    if type(value) not in {int, float}:
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile contains an invalid number",
            identity=identity,
        )


def _extra_body_digest(value: object) -> str:
    return canonical_digest(value)


def _profile_user_agent(settings: LlmSettings) -> str | None:
    headers = settings.default_headers
    if headers is None:
        return None
    if set(headers) != {"User-Agent"} or not isinstance(headers["User-Agent"], str):
        raise AoxCutoverLaunchError(
            "aox_launch_profile_settings_unsupported",
            "AOX launch profile cannot persist an open LLM header mapping",
        )
    return headers["User-Agent"]


def _reject_credential_bearing_url(value: object, *, identity: str) -> None:
    parsed = urlsplit(str(value))
    if (
        parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        _reject(
            "aox_launch_profile_secret_forbidden",
            "AOX launch profile cannot persist credential-bearing URLs",
            identity=identity,
        )


def _settings_payload(settings: OpenZymeSettings) -> dict[str, object]:
    return {
        "llm": {
            "model": settings.llm.model,
            "base_url": settings.llm.base_url,
            "extra_body_digest": _extra_body_digest(settings.llm.extra_body),
            "user_agent": _profile_user_agent(settings.llm),
            "use_responses_api": settings.llm.use_responses_api,
            "max_tokens": settings.llm.max_tokens,
            "timeout": settings.llm.timeout,
            "max_retries": settings.llm.max_retries,
            "temperature": settings.llm.temperature,
            "structured_output_method": settings.llm.structured_output_method,
            "structured_output_retry_backoff_seconds": (
                settings.llm.structured_output_retry_backoff_seconds
            ),
            "purpose_policies": {
                name: {
                    "max_tokens": policy.max_tokens,
                    "timeout": policy.timeout,
                    "max_retries": policy.max_retries,
                    "structured_output_method": policy.structured_output_method,
                    "structured_output_retry_backoff_seconds": (
                        policy.structured_output_retry_backoff_seconds
                    ),
                }
                for name, policy in sorted(settings.llm.purpose_policies.items())
            },
            "context_window_tokens": settings.llm.context_window_tokens,
            "default_output_tokens": settings.llm.default_output_tokens,
            "context_warn_ratio": settings.llm.context_warn_ratio,
            "context_auto_compact_ratio": settings.llm.context_auto_compact_ratio,
            "context_emergency_ratio": settings.llm.context_emergency_ratio,
            "tokenizer_enabled": settings.llm.tokenizer_enabled,
        },
        "research": {
            "max_units": settings.research.max_units,
            "allow_clarification": settings.research.allow_clarification,
            "max_research_iterations": settings.research.max_research_iterations,
            "max_react_tool_calls": settings.research.max_react_tool_calls,
            "max_concurrent_research_units": (
                settings.research.max_concurrent_research_units
            ),
            "tavily_max_results": settings.research.tavily_max_results,
            "tavily_topic": settings.research.tavily_topic,
            "mcp_tool_allowlist": list(settings.research.mcp_tool_allowlist),
            "tavily_timeout_seconds": settings.research.tavily_timeout_seconds,
            "pubmed_tool": settings.research.pubmed_tool,
            "provider_timeout_seconds": settings.research.provider_timeout_seconds,
            "provider_max_attempts": settings.research.provider_max_attempts,
        },
        "tracing": {
            "enabled": settings.tracing.enabled,
            "project_name": settings.tracing.project_name,
        },
        "host_cli": {
            "base_url": settings.host_cli.base_url,
            "project_id": settings.host_cli.project_id,
            "output_format": settings.host_cli.output_format,
        },
        "host_api": {
            "bind_host": settings.host_api.bind_host,
            "bind_port": settings.host_api.bind_port,
            "deployment_profile": settings.host_api.deployment_profile,
            "debug_enabled": settings.host_api.debug_enabled,
        },
        "v3_background_runtime": {
            "enabled": settings.v3_background_runtime.enabled,
            "poll_interval_seconds": settings.v3_background_runtime.poll_interval_seconds,
            "max_signals_per_tick": settings.v3_background_runtime.max_signals_per_tick,
            "max_steps_per_agent": settings.v3_background_runtime.max_steps_per_agent,
            "shutdown_timeout_seconds": (
                settings.v3_background_runtime.shutdown_timeout_seconds
            ),
        },
        "execution": {
            "backend": settings.execution.backend,
            "hpc_runner_config": settings.execution.hpc_runner_config,
        },
        "limits": {
            "provider_limits": dict(sorted(settings.limits.provider_limits.items())),
        },
        "test": {
            "enable_live_llm": settings.test.enable_live_llm,
            "enable_live_tavily": settings.test.enable_live_tavily,
            "enable_live_hpc": settings.test.enable_live_hpc,
            "enable_live_e2e": settings.test.enable_live_e2e,
            "enable_quality_eval": settings.test.enable_quality_eval,
            "upload_langsmith": settings.test.upload_langsmith,
            "live_llm": {
                "max_tokens": settings.test.live_llm.max_tokens,
                "timeout": settings.test.live_llm.timeout,
                "max_retries": settings.test.live_llm.max_retries,
                "structured_output_method": (
                    settings.test.live_llm.structured_output_method
                ),
                "structured_output_retry_backoff_seconds": (
                    settings.test.live_llm.structured_output_retry_backoff_seconds
                ),
            },
        },
        "reliability": {
            "shadow_observability": settings.reliability.shadow_observability.value,
            "controlled_operation_owner_policy": (
                settings.reliability.controlled_operation_owner_policy.value
            ),
            "durable_execution_route_allowlist": list(
                settings.reliability.durable_execution_route_allowlist
            ),
            "runtime_drain_contract": settings.reliability.runtime_drain_contract.value,
            "mutation_closure_mode": settings.reliability.mutation_closure_mode.value,
            "shadow_max_observations": settings.reliability.shadow_max_observations,
        },
    }


def build_aox_cutover_launch_profile(
    *,
    settings: OpenZymeSettings,
    ledger_path: Path,
    source_commit: str,
    config_digest: str,
    created_at: str | None = None,
) -> dict[str, object]:
    resolved_ledger = ledger_path.expanduser().resolve()
    payload = {
        "schema_id": AOX_CUTOVER_LAUNCH_PROFILE_SCHEMA_ID,
        "source_commit": source_commit,
        "config_digest": config_digest,
        "ledger_path": str(resolved_ledger),
        "settings": _settings_payload(settings),
        "created_at": created_at or datetime.now(UTC).isoformat(),
    }
    return normalize_aox_cutover_launch_profile(
        {**payload, "profile_digest": canonical_digest(payload)}
    )


def _normalize_settings_payload(value: object) -> dict[str, Any]:
    settings = _closed_mapping(
        value, _SETTINGS_FIELDS, identity="launch_profile.settings"
    )
    llm = _closed_mapping(
        settings["llm"], _LLM_FIELDS, identity="launch_profile.settings.llm"
    )
    for name in ("model", "base_url", "structured_output_method"):
        _require_string(llm[name], identity=f"launch_profile.settings.llm.{name}")
    _reject_credential_bearing_url(
        llm["base_url"], identity="launch_profile.settings.llm.base_url"
    )
    _require_string(
        llm["user_agent"],
        identity="launch_profile.settings.llm.user_agent",
        optional=True,
    )
    if _DIGEST.fullmatch(str(llm.get("extra_body_digest") or "")) is None:
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile extra-body digest is invalid",
            identity="launch_profile.settings.llm.extra_body_digest",
        )
    for name in ("use_responses_api", "tokenizer_enabled"):
        _require_bool(llm[name], identity=f"launch_profile.settings.llm.{name}")
    for name in ("max_tokens", "context_window_tokens", "default_output_tokens"):
        _require_int(
            llm[name], identity=f"launch_profile.settings.llm.{name}", optional=True
        )
    _require_int(llm["max_retries"], identity="launch_profile.settings.llm.max_retries")
    for name in (
        "timeout",
        "temperature",
        "structured_output_retry_backoff_seconds",
        "context_warn_ratio",
        "context_auto_compact_ratio",
        "context_emergency_ratio",
    ):
        _require_number(
            llm[name],
            identity=f"launch_profile.settings.llm.{name}",
            optional=name == "timeout",
        )
    policies = llm["purpose_policies"]
    if not isinstance(policies, Mapping) or any(
        not isinstance(name, str) or _SAFE_KEY.fullmatch(name) is None
        for name in policies
    ):
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile purpose policies are invalid",
            identity="launch_profile.settings.llm.purpose_policies",
        )
    for name, raw_policy in policies.items():
        policy = _closed_mapping(
            raw_policy,
            _PURPOSE_POLICY_FIELDS,
            identity=f"launch_profile.settings.llm.purpose_policies.{name}",
        )
        _require_int(
            policy["max_tokens"],
            identity=f"launch_profile.settings.llm.purpose_policies.{name}.max_tokens",
            optional=True,
        )
        _require_number(
            policy["timeout"],
            identity=f"launch_profile.settings.llm.purpose_policies.{name}.timeout",
            optional=True,
        )
        _require_int(
            policy["max_retries"],
            identity=f"launch_profile.settings.llm.purpose_policies.{name}.max_retries",
            optional=True,
        )
        _require_string(
            policy["structured_output_method"],
            identity=f"launch_profile.settings.llm.purpose_policies.{name}.structured_output_method",
            optional=True,
        )
        _require_number(
            policy["structured_output_retry_backoff_seconds"],
            identity=f"launch_profile.settings.llm.purpose_policies.{name}.structured_output_retry_backoff_seconds",
            optional=True,
        )

    research = _closed_mapping(
        settings["research"],
        _RESEARCH_FIELDS,
        identity="launch_profile.settings.research",
    )
    for name in (
        "max_units",
        "max_research_iterations",
        "max_react_tool_calls",
        "max_concurrent_research_units",
        "tavily_max_results",
        "provider_max_attempts",
    ):
        _require_int(
            research[name], identity=f"launch_profile.settings.research.{name}"
        )
    _require_bool(
        research["allow_clarification"],
        identity="launch_profile.settings.research.allow_clarification",
    )
    for name in ("tavily_timeout_seconds", "provider_timeout_seconds"):
        _require_number(
            research[name], identity=f"launch_profile.settings.research.{name}"
        )
    for name in ("tavily_topic", "pubmed_tool"):
        _require_string(
            research[name], identity=f"launch_profile.settings.research.{name}"
        )
    allowlist = research["mcp_tool_allowlist"]
    if not isinstance(allowlist, list) or any(
        not isinstance(item, str) or not item for item in allowlist
    ):
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile MCP allowlist is invalid",
            identity="launch_profile.settings.research.mcp_tool_allowlist",
        )

    tracing = _closed_mapping(
        settings["tracing"], _TRACING_FIELDS, identity="launch_profile.settings.tracing"
    )
    _require_bool(
        tracing["enabled"], identity="launch_profile.settings.tracing.enabled"
    )
    _require_string(
        tracing["project_name"], identity="launch_profile.settings.tracing.project_name"
    )
    host_cli = _closed_mapping(
        settings["host_cli"],
        _HOST_CLI_FIELDS,
        identity="launch_profile.settings.host_cli",
    )
    _require_string(
        host_cli["base_url"], identity="launch_profile.settings.host_cli.base_url"
    )
    _reject_credential_bearing_url(
        host_cli["base_url"], identity="launch_profile.settings.host_cli.base_url"
    )
    _require_string(
        host_cli["project_id"],
        identity="launch_profile.settings.host_cli.project_id",
        optional=True,
    )
    _require_string(
        host_cli["output_format"],
        identity="launch_profile.settings.host_cli.output_format",
    )
    host_api = _closed_mapping(
        settings["host_api"],
        _HOST_API_FIELDS,
        identity="launch_profile.settings.host_api",
    )
    for name in ("bind_host", "deployment_profile"):
        _require_string(
            host_api[name], identity=f"launch_profile.settings.host_api.{name}"
        )
    _require_int(
        host_api["bind_port"], identity="launch_profile.settings.host_api.bind_port"
    )
    _require_bool(
        host_api["debug_enabled"],
        identity="launch_profile.settings.host_api.debug_enabled",
    )

    background = _closed_mapping(
        settings["v3_background_runtime"],
        _BACKGROUND_FIELDS,
        identity="launch_profile.settings.v3_background_runtime",
    )
    _require_bool(
        background["enabled"],
        identity="launch_profile.settings.v3_background_runtime.enabled",
    )
    for name in ("max_signals_per_tick", "max_steps_per_agent"):
        _require_int(
            background[name],
            identity=f"launch_profile.settings.v3_background_runtime.{name}",
        )
    for name in ("poll_interval_seconds", "shutdown_timeout_seconds"):
        _require_number(
            background[name],
            identity=f"launch_profile.settings.v3_background_runtime.{name}",
        )
    execution = _closed_mapping(
        settings["execution"],
        _EXECUTION_FIELDS,
        identity="launch_profile.settings.execution",
    )
    _require_string(
        execution["backend"], identity="launch_profile.settings.execution.backend"
    )
    _require_string(
        execution["hpc_runner_config"],
        identity="launch_profile.settings.execution.hpc_runner_config",
        optional=True,
    )

    limits = _closed_mapping(
        settings["limits"], _LIMITS_FIELDS, identity="launch_profile.settings.limits"
    )
    provider_limits = limits["provider_limits"]
    if (
        not isinstance(provider_limits, Mapping)
        or not provider_limits
        or any(
            not isinstance(name, str)
            or _SAFE_KEY.fullmatch(name) is None
            or type(limit) is not int
            or limit <= 0
            for name, limit in provider_limits.items()
        )
    ):
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile provider limits are invalid",
            identity="launch_profile.settings.limits.provider_limits",
        )

    test = _closed_mapping(
        settings["test"], _TEST_FIELDS, identity="launch_profile.settings.test"
    )
    for name in (
        "enable_live_llm",
        "enable_live_tavily",
        "enable_live_hpc",
        "enable_live_e2e",
        "enable_quality_eval",
        "upload_langsmith",
    ):
        _require_bool(test[name], identity=f"launch_profile.settings.test.{name}")
    live_llm = _closed_mapping(
        test["live_llm"],
        _LIVE_LLM_FIELDS,
        identity="launch_profile.settings.test.live_llm",
    )
    _require_int(
        live_llm["max_tokens"],
        identity="launch_profile.settings.test.live_llm.max_tokens",
        optional=True,
    )
    _require_number(
        live_llm["timeout"],
        identity="launch_profile.settings.test.live_llm.timeout",
        optional=True,
    )
    _require_int(
        live_llm["max_retries"],
        identity="launch_profile.settings.test.live_llm.max_retries",
        optional=True,
    )
    _require_string(
        live_llm["structured_output_method"],
        identity="launch_profile.settings.test.live_llm.structured_output_method",
        optional=True,
    )
    _require_number(
        live_llm["structured_output_retry_backoff_seconds"],
        identity="launch_profile.settings.test.live_llm.structured_output_retry_backoff_seconds",
        optional=True,
    )

    reliability = _closed_mapping(
        settings["reliability"],
        _RELIABILITY_FIELDS,
        identity="launch_profile.settings.reliability",
    )
    for name in (
        "shadow_observability",
        "controlled_operation_owner_policy",
        "runtime_drain_contract",
        "mutation_closure_mode",
    ):
        _require_string(
            reliability[name], identity=f"launch_profile.settings.reliability.{name}"
        )
    try:
        ShadowObservabilityMode(reliability["shadow_observability"])
        owner_policy = ControlledOperationOwnerPolicy(
            reliability["controlled_operation_owner_policy"]
        )
        RuntimeDrainContract(reliability["runtime_drain_contract"])
        MutationClosureMode(reliability["mutation_closure_mode"])
    except ValueError:
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile reliability enum is invalid",
            identity="launch_profile.settings.reliability",
        )
    if owner_policy not in {
        ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1,
        ControlledOperationOwnerPolicy.DURABLE_ONLY_V1,
    }:
        _reject(
            "aox_launch_profile_owner_policy_invalid",
            "AOX launch profile rejects the legacy controlled-operation owner",
            identity=(
                "launch_profile.settings.reliability.controlled_operation_owner_policy"
            ),
        )
    routes = reliability["durable_execution_route_allowlist"]
    if (
        not isinstance(routes, list)
        or routes != sorted(set(routes))
        or any(not isinstance(item, str) or not item for item in routes)
    ):
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile durable route allowlist is invalid",
            identity="launch_profile.settings.reliability.durable_execution_route_allowlist",
        )
    _require_int(
        reliability["shadow_max_observations"],
        identity="launch_profile.settings.reliability.shadow_max_observations",
    )
    return settings


def normalize_aox_cutover_launch_profile(
    value: Mapping[str, object],
) -> dict[str, object]:
    profile = _closed_mapping(value, _PROFILE_FIELDS, identity="launch_profile")
    if profile.get("schema_id") != AOX_CUTOVER_LAUNCH_PROFILE_SCHEMA_ID:
        _reject(
            "aox_launch_profile_schema_invalid",
            "only the current AOX launch profile is accepted",
            identity="launch_profile.schema_id",
        )
    if _COMMIT.fullmatch(str(profile.get("source_commit") or "")) is None:
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile source commit is invalid",
            identity="launch_profile.source_commit",
        )
    if _DIGEST.fullmatch(str(profile.get("config_digest") or "")) is None:
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile config digest is invalid",
            identity="launch_profile.config_digest",
        )
    ledger_path = profile.get("ledger_path")
    if not isinstance(ledger_path, str) or not Path(ledger_path).is_absolute():
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile ledger path is invalid",
            identity="launch_profile.ledger_path",
        )
    try:
        created_at = datetime.fromisoformat(str(profile.get("created_at") or ""))
    except ValueError:
        created_at = None
    if created_at is None or created_at.tzinfo is None:
        _reject(
            "aox_launch_profile_schema_invalid",
            "AOX launch profile timestamp is invalid",
            identity="launch_profile.created_at",
        )
    _normalize_settings_payload(profile.get("settings"))
    payload = {key: item for key, item in profile.items() if key != "profile_digest"}
    if profile.get("profile_digest") != canonical_digest(payload):
        _reject(
            "aox_launch_profile_digest_mismatch",
            "AOX launch profile digest does not reproduce",
            identity="launch_profile.profile_digest",
        )
    return profile


def launch_profile_digest(value: Mapping[str, object]) -> str:
    """Return the self-verifying digest that binds the closed profile payload."""

    return str(normalize_aox_cutover_launch_profile(value)["profile_digest"])


def _ambient_extra_body(*, model: str, base_url: str) -> dict[str, Any] | None:
    raw = os.getenv("OPENZYME_LLM_EXTRA_BODY")
    if raw not in {None, ""}:
        try:
            parsed = json.loads(str(raw))
        except (TypeError, json.JSONDecodeError) as exc:
            raise AoxCutoverLaunchError(
                "aox_launch_profile_ambient_invalid",
                "ambient credential-bearing LLM extension is invalid",
            ) from exc
        if not isinstance(parsed, dict):
            raise AoxCutoverLaunchError(
                "aox_launch_profile_ambient_invalid",
                "ambient credential-bearing LLM extension is invalid",
            )
        return dict(parsed)
    if "open.bigmodel.cn" in base_url or model.startswith("glm-"):
        return {"provider": "bigmodel"}
    return None


def resolve_aox_cutover_launch_profile(
    value: Mapping[str, object],
    *,
    install_provider_environment: bool = False,
) -> tuple[OpenZymeSettings, Path]:
    profile = normalize_aox_cutover_launch_profile(value)
    load_env_files()
    settings = dict(profile["settings"])
    llm = dict(settings["llm"])
    research = dict(settings["research"])
    tracing = dict(settings["tracing"])
    host_cli = dict(settings["host_cli"])
    host_api = dict(settings["host_api"])
    background = dict(settings["v3_background_runtime"])
    execution = dict(settings["execution"])
    limits = dict(settings["limits"])
    test = dict(settings["test"])
    live_llm = dict(test["live_llm"])
    reliability = dict(settings["reliability"])
    ledger_path = Path(str(profile["ledger_path"]))
    extra_body = _ambient_extra_body(
        model=str(llm["model"]),
        base_url=str(llm["base_url"]),
    )
    if _extra_body_digest(extra_body) != llm["extra_body_digest"]:
        raise AoxCutoverLaunchError(
            "aox_launch_profile_ambient_conflict",
            "ambient credential-bearing LLM extension differs from the pinned profile",
        )
    if os.getenv("OPENZYME_HOST_AUTH_PRINCIPALS_JSON") not in {None, ""}:
        raise AoxCutoverLaunchError(
            "aox_launch_profile_ambient_conflict",
            "formal local launch cannot inherit shared Host principals",
        )
    purpose_policies = {
        str(name): LlmPurposePolicy(**dict(raw))
        for name, raw in dict(llm["purpose_policies"]).items()
    }
    resolved = OpenZymeSettings(
        llm=LlmSettings(
            api_key=os.getenv("OPENZYME_LLM_API_KEY")
            or os.getenv("MICU_API_KEY")
            or None,
            model=str(llm["model"]),
            base_url=str(llm["base_url"]),
            extra_body=extra_body,
            default_headers=(
                None
                if llm["user_agent"] is None
                else {"User-Agent": str(llm["user_agent"])}
            ),
            use_responses_api=bool(llm["use_responses_api"]),
            max_tokens=llm["max_tokens"],
            timeout=llm["timeout"],
            max_retries=int(llm["max_retries"]),
            temperature=float(llm["temperature"]),
            structured_output_method=str(llm["structured_output_method"]),
            structured_output_retry_backoff_seconds=float(
                llm["structured_output_retry_backoff_seconds"]
            ),
            purpose_policies=purpose_policies,
            context_window_tokens=llm["context_window_tokens"],
            default_output_tokens=llm["default_output_tokens"],
            context_warn_ratio=float(llm["context_warn_ratio"]),
            context_auto_compact_ratio=float(llm["context_auto_compact_ratio"]),
            context_emergency_ratio=float(llm["context_emergency_ratio"]),
            tokenizer_enabled=bool(llm["tokenizer_enabled"]),
        ),
        research=ResearchSettings(
            max_units=int(research["max_units"]),
            allow_clarification=bool(research["allow_clarification"]),
            max_research_iterations=int(research["max_research_iterations"]),
            max_react_tool_calls=int(research["max_react_tool_calls"]),
            max_concurrent_research_units=int(
                research["max_concurrent_research_units"]
            ),
            tavily_api_key=os.getenv("TAVILY_API_KEY"),
            tavily_max_results=int(research["tavily_max_results"]),
            tavily_topic=str(research["tavily_topic"]),
            mcp_tool_allowlist=tuple(research["mcp_tool_allowlist"]),
            tavily_timeout_seconds=float(research["tavily_timeout_seconds"]),
            pubmed_email=os.getenv("OPENZYME_NCBI_EMAIL") or os.getenv("NCBI_EMAIL"),
            pubmed_tool=str(research["pubmed_tool"]),
            pubmed_api_key=os.getenv("OPENZYME_NCBI_API_KEY")
            or os.getenv("NCBI_API_KEY"),
            semantic_scholar_api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
            provider_timeout_seconds=float(research["provider_timeout_seconds"]),
            provider_max_attempts=int(research["provider_max_attempts"]),
        ),
        tracing=TracingSettings(
            enabled=bool(tracing["enabled"]),
            project_name=str(tracing["project_name"]),
        ),
        host_cli=HostCliSettings(
            base_url=str(host_cli["base_url"]),
            project_id=host_cli["project_id"],
            output_format=str(host_cli["output_format"]),
            auth_token=os.getenv("OPENZYME_HOST_AUTH_TOKEN"),
        ),
        host_api=HostApiSettings(
            bind_host=str(host_api["bind_host"]),
            bind_port=int(host_api["bind_port"]),
            deployment_profile=str(host_api["deployment_profile"]),
            principals=(),
            debug_enabled=bool(host_api["debug_enabled"]),
        ),
        v3_background_runtime=V3BackgroundRuntimeSettings(
            enabled=bool(background["enabled"]),
            poll_interval_seconds=float(background["poll_interval_seconds"]),
            max_signals_per_tick=int(background["max_signals_per_tick"]),
            max_steps_per_agent=int(background["max_steps_per_agent"]),
            shutdown_timeout_seconds=float(background["shutdown_timeout_seconds"]),
        ),
        execution=ExecutionSettings(
            backend=str(execution["backend"]),
            hpc_runner_config=execution["hpc_runner_config"],
        ),
        limits=LimiterSettings(
            provider_limits={
                str(name): int(limit)
                for name, limit in dict(limits["provider_limits"]).items()
            }
        ),
        test=TestSettings(
            enable_live_llm=bool(test["enable_live_llm"]),
            enable_live_tavily=bool(test["enable_live_tavily"]),
            enable_live_hpc=bool(test["enable_live_hpc"]),
            enable_live_e2e=bool(test["enable_live_e2e"]),
            enable_quality_eval=bool(test["enable_quality_eval"]),
            upload_langsmith=bool(test["upload_langsmith"]),
            live_llm=LiveLlmTestSettings(
                max_tokens=live_llm["max_tokens"],
                timeout=live_llm["timeout"],
                max_retries=live_llm["max_retries"],
                structured_output_method=live_llm["structured_output_method"],
                structured_output_retry_backoff_seconds=live_llm[
                    "structured_output_retry_backoff_seconds"
                ],
                token_ledger_path=str(ledger_path),
            ),
        ),
        reliability=ReliabilityRefactorSettings(
            shadow_observability=ShadowObservabilityMode(
                reliability["shadow_observability"]
            ),
            controlled_operation_owner_policy=ControlledOperationOwnerPolicy(
                reliability["controlled_operation_owner_policy"]
            ),
            durable_execution_route_allowlist=tuple(
                reliability["durable_execution_route_allowlist"]
            ),
            runtime_drain_contract=RuntimeDrainContract(
                reliability["runtime_drain_contract"]
            ),
            mutation_closure_mode=MutationClosureMode(
                reliability["mutation_closure_mode"]
            ),
            shadow_max_observations=int(reliability["shadow_max_observations"]),
        ),
    )
    # Provider adapters still read the non-sensitive NCBI tool label from their
    # own closed environment seam. Install only this profile-owned value; all
    # credential/email variables remain ambient.
    if install_provider_environment:
        os.environ["OPENZYME_NCBI_TOOL"] = resolved.research.pubmed_tool
    return resolved, ledger_path


__all__ = [
    "AOX_CUTOVER_LAUNCH_PROFILE_FILENAME",
    "AOX_CUTOVER_LAUNCH_PROFILE_SCHEMA_ID",
    "build_aox_cutover_launch_profile",
    "launch_profile_digest",
    "normalize_aox_cutover_launch_profile",
    "resolve_aox_cutover_launch_profile",
]
