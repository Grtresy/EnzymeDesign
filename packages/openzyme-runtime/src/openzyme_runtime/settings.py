from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .limits import DEFAULT_PROVIDER_LIMITS
from .environment_contract import credential_safe_source_projection
from .environment_contract import EnvironmentFieldDescriptor
from .environment_contract import field_map
from .live_token_ledger import DEFAULT_LIVE_MICU_TOKEN_LEDGER_PATH
from .live_token_ledger import DEFAULT_LIVE_MICU_TOKEN_LEDGER_RELATIVE_PATH
from .live_token_ledger import LIVE_MICU_TOKEN_LEDGER_PATH_ENV
from .live_token_ledger import resolve_live_micu_token_ledger_path
from .reliability import ReliabilityRefactorSettings
from .reliability import reliability_environment_fields


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENV_FILES = (".env", ".env.local")
DEFAULT_OPENAI_COMPAT_BASE_URL = "https://www.micuapi.ai/v1"
DEFAULT_OPENAI_COMPAT_MODEL = "gpt-5.4-mini"
DEFAULT_OPENAI_COMPAT_EXTRA_BODY: dict[str, Any] | None = None
_BIGMODEL_EXTRA_BODY = {"provider": "bigmodel"}
DEFAULT_OPENAI_COMPAT_USER_AGENT = (
    "codex_cli_rs/0.77.0 (Windows 10.0.26100; x86_64) WindowsTerminal"
)
DEFAULT_OPENAI_COMPAT_USE_RESPONSES_API = True
DEFAULT_LLM_STRUCTURED_OUTPUT_METHOD = "function_calling"
DEFAULT_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS = 1.0
DEFAULT_HOST_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_HOST_API_BIND_HOST = "127.0.0.1"
DEFAULT_HOST_API_BIND_PORT = 8000
HOST_API_LOCAL_DEPLOYMENT_PROFILE = "local-dev"
HOST_API_DEPLOYMENT_PROFILES = frozenset({HOST_API_LOCAL_DEPLOYMENT_PROFILE, "shared"})
HOST_API_LOOPBACK_BIND_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
LIMIT_ENV_VARS = {
    "global": "OPENZYME_LIMIT_GLOBAL_CONCURRENCY",
    "session": "OPENZYME_LIMIT_SESSION_CONCURRENCY",
    "agent": "OPENZYME_LIMIT_AGENT_CONCURRENCY",
    "llm_provider": "OPENZYME_LIMIT_LLM_PROVIDER_CONCURRENCY",
    "research_provider": "OPENZYME_LIMIT_RESEARCH_PROVIDER_CONCURRENCY",
    "execution_provider": "OPENZYME_LIMIT_EXECUTION_PROVIDER_CONCURRENCY",
}
LLM_PURPOSES = (
    "intake",
    "research",
    "design",
    "report_review",
    "v3_harness_loop",
    "deep_research_brief",
    "deep_research_supervisor",
    "deep_research_researcher",
    "deep_research_synthesis",
)


_LLM_PURPOSE_ENVIRONMENT_FIELD_SPECS = (
    ("max_tokens", "optional_integer"),
    ("timeout", "optional_number"),
    ("max_retries", "optional_integer"),
    ("structured_output_method", "string"),
    ("structured_output_retry_backoff_seconds", "optional_number"),
)


def _purpose_environment_fields() -> tuple[EnvironmentFieldDescriptor, ...]:
    fields: list[EnvironmentFieldDescriptor] = []
    for purpose in LLM_PURPOSES:
        for field_name, value_kind in _LLM_PURPOSE_ENVIRONMENT_FIELD_SPECS:
            fields.append(
                EnvironmentFieldDescriptor(
                    setting_path=f"llm.purpose_policies.{purpose}.{field_name}",
                    environment_names=(
                        f"OPENZYME_LLM_{purpose.upper()}_{field_name.upper()}",
                    ),
                    value_kind=value_kind,
                    safe_generic_default=None,
                )
            )
    return tuple(fields)


_OPENZYME_SETTINGS_ENVIRONMENT_FIELDS = (
    EnvironmentFieldDescriptor(
        setting_path="llm.api_key",
        environment_names=("OPENZYME_LLM_API_KEY", "MICU_API_KEY"),
        value_kind="credential",
        safe_generic_default=None,
        identity_mode="credential_presence",
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.model",
        environment_names=("OPENZYME_LLM_MODEL",),
        value_kind="string",
        safe_generic_default=DEFAULT_OPENAI_COMPAT_MODEL,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.base_url",
        environment_names=("OPENZYME_LLM_BASE_URL",),
        value_kind="string",
        safe_generic_default=DEFAULT_OPENAI_COMPAT_BASE_URL,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.extra_body",
        environment_names=("OPENZYME_LLM_EXTRA_BODY",),
        value_kind="json_object",
        safe_generic_default=None,
        identity_mode="private_digest",
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.default_headers",
        environment_names=("OPENZYME_LLM_USER_AGENT",),
        value_kind="private_string",
        safe_generic_default=DEFAULT_OPENAI_COMPAT_USER_AGENT,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.use_responses_api",
        environment_names=("OPENZYME_LLM_USE_RESPONSES_API",),
        value_kind="boolean",
        safe_generic_default=DEFAULT_OPENAI_COMPAT_USE_RESPONSES_API,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.max_tokens",
        environment_names=("OPENZYME_LLM_MAX_TOKENS",),
        value_kind="optional_integer",
        safe_generic_default=None,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.timeout",
        environment_names=("OPENZYME_LLM_TIMEOUT",),
        value_kind="optional_number",
        safe_generic_default=None,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.max_retries",
        environment_names=("OPENZYME_LLM_MAX_RETRIES",),
        value_kind="integer",
        safe_generic_default=5,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.temperature",
        environment_names=("OPENZYME_LLM_TEMPERATURE",),
        value_kind="number",
        safe_generic_default=0.0,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.structured_output_method",
        environment_names=("OPENZYME_LLM_STRUCTURED_OUTPUT_METHOD",),
        value_kind="string",
        safe_generic_default=DEFAULT_LLM_STRUCTURED_OUTPUT_METHOD,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.structured_output_retry_backoff_seconds",
        environment_names=("OPENZYME_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS",),
        value_kind="number",
        safe_generic_default=DEFAULT_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.context_window_tokens",
        environment_names=("OPENZYME_LLM_CONTEXT_WINDOW_TOKENS",),
        value_kind="optional_integer",
        safe_generic_default=None,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.default_output_tokens",
        environment_names=("OPENZYME_LLM_DEFAULT_OUTPUT_TOKENS",),
        value_kind="optional_integer",
        safe_generic_default=None,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.context_warn_ratio",
        environment_names=("OPENZYME_LLM_CONTEXT_WARN_RATIO",),
        value_kind="number",
        safe_generic_default=0.80,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.context_auto_compact_ratio",
        environment_names=("OPENZYME_LLM_CONTEXT_AUTO_COMPACT_RATIO",),
        value_kind="number",
        safe_generic_default=0.85,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.context_emergency_ratio",
        environment_names=("OPENZYME_LLM_CONTEXT_EMERGENCY_RATIO",),
        value_kind="number",
        safe_generic_default=0.90,
    ),
    EnvironmentFieldDescriptor(
        setting_path="llm.tokenizer_enabled",
        environment_names=("OPENZYME_LLM_TOKENIZER_ENABLED",),
        value_kind="boolean",
        safe_generic_default=False,
        empty_uses_fallback=False,
    ),
    *_purpose_environment_fields(),
    EnvironmentFieldDescriptor(
        setting_path="research.max_units",
        environment_names=("OPENZYME_RESEARCH_MAX_UNITS",),
        value_kind="integer",
        safe_generic_default=3,
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.allow_clarification",
        environment_names=("OPENZYME_RESEARCH_ALLOW_CLARIFICATION",),
        value_kind="boolean",
        safe_generic_default=False,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.max_research_iterations",
        environment_names=("OPENZYME_RESEARCH_MAX_ITERATIONS",),
        value_kind="integer",
        safe_generic_default=3,
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.max_react_tool_calls",
        environment_names=("OPENZYME_RESEARCH_MAX_REACT_TOOL_CALLS",),
        value_kind="integer",
        safe_generic_default=4,
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.max_concurrent_research_units",
        environment_names=("OPENZYME_RESEARCH_MAX_CONCURRENT_UNITS",),
        value_kind="integer",
        safe_generic_default=3,
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.tavily_api_key",
        environment_names=("TAVILY_API_KEY",),
        value_kind="credential",
        safe_generic_default=None,
        identity_mode="credential_presence",
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.tavily_max_results",
        environment_names=("OPENZYME_TAVILY_MAX_RESULTS",),
        value_kind="integer",
        safe_generic_default=3,
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.tavily_topic",
        environment_names=("OPENZYME_TAVILY_TOPIC",),
        value_kind="string",
        safe_generic_default="general",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.mcp_tool_allowlist",
        environment_names=("OPENZYME_RESEARCH_MCP_TOOL_ALLOWLIST",),
        value_kind="string_list",
        safe_generic_default=[],
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.tavily_timeout_seconds",
        environment_names=("OPENZYME_TAVILY_TIMEOUT_SECONDS",),
        value_kind="number",
        safe_generic_default=30.0,
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.pubmed_email",
        environment_names=("OPENZYME_NCBI_EMAIL", "NCBI_EMAIL"),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.pubmed_tool",
        environment_names=("OPENZYME_NCBI_TOOL", "NCBI_TOOL"),
        value_kind="string",
        safe_generic_default="openzyme",
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.pubmed_api_key",
        environment_names=("OPENZYME_NCBI_API_KEY", "NCBI_API_KEY"),
        value_kind="credential",
        safe_generic_default=None,
        identity_mode="credential_presence",
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.semantic_scholar_api_key",
        environment_names=("SEMANTIC_SCHOLAR_API_KEY",),
        value_kind="credential",
        safe_generic_default=None,
        identity_mode="credential_presence",
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.provider_timeout_seconds",
        environment_names=("OPENZYME_RESEARCH_PROVIDER_TIMEOUT_SECONDS",),
        value_kind="number",
        safe_generic_default=30.0,
    ),
    EnvironmentFieldDescriptor(
        setting_path="research.provider_max_attempts",
        environment_names=("OPENZYME_RESEARCH_PROVIDER_MAX_ATTEMPTS",),
        value_kind="integer",
        safe_generic_default=3,
    ),
    EnvironmentFieldDescriptor(
        setting_path="tracing.enabled",
        environment_names=("OPENZYME_LANGSMITH_TRACING", "LANGSMITH_TRACING"),
        value_kind="boolean",
        safe_generic_default=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="tracing.project_name",
        environment_names=("OPENZYME_LANGSMITH_PROJECT", "LANGSMITH_PROJECT"),
        value_kind="private_string",
        safe_generic_default="openzyme-v3",
        identity_mode="private_digest",
    ),
    EnvironmentFieldDescriptor(
        setting_path="host_cli.base_url",
        environment_names=("OPENZYME_HOST_BASE_URL",),
        value_kind="string",
        safe_generic_default=DEFAULT_HOST_BASE_URL,
        empty_uses_fallback=False,
        candidate_identity=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="host_cli.project_id",
        environment_names=("OPENZYME_PROJECT_ID",),
        value_kind="string",
        safe_generic_default=None,
        candidate_identity=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="host_cli.output_format",
        environment_names=("OPENZYME_OUTPUT_FORMAT",),
        value_kind="string",
        safe_generic_default="text",
        empty_uses_fallback=False,
        candidate_identity=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="host_cli.auth_token",
        environment_names=("OPENZYME_HOST_AUTH_TOKEN",),
        value_kind="credential",
        safe_generic_default=None,
        identity_mode="credential_presence",
        candidate_identity=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="host_api.bind_host",
        environment_names=("OPENZYME_HOST_API_HOST",),
        value_kind="string",
        safe_generic_default=DEFAULT_HOST_API_BIND_HOST,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="host_api.bind_port",
        environment_names=("OPENZYME_HOST_API_PORT",),
        value_kind="integer",
        safe_generic_default=DEFAULT_HOST_API_BIND_PORT,
    ),
    EnvironmentFieldDescriptor(
        setting_path="host_api.deployment_profile",
        environment_names=("OPENZYME_HOST_DEPLOYMENT_PROFILE",),
        value_kind="string",
        safe_generic_default=HOST_API_LOCAL_DEPLOYMENT_PROFILE,
        empty_uses_fallback=False,
        strip_value=True,
    ),
    EnvironmentFieldDescriptor(
        setting_path="host_api.principals",
        environment_names=("OPENZYME_HOST_AUTH_PRINCIPALS_JSON",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="credential_presence",
    ),
    EnvironmentFieldDescriptor(
        setting_path="host_api.debug_enabled",
        environment_names=("OPENZYME_HOST_DEBUG_ENABLED",),
        value_kind="boolean",
        safe_generic_default=False,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.https_origin",
        environment_names=("OPENZYME_REPOSITORY_HTTPS_ORIGIN",),
        value_kind="string",
        safe_generic_default=None,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.bare_repository_root",
        environment_names=("OPENZYME_REPOSITORY_BARE_ROOT",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.lfs_object_root",
        environment_names=("OPENZYME_REPOSITORY_LFS_ROOT",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.backup_root",
        environment_names=("OPENZYME_REPOSITORY_BACKUP_ROOT",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.credential_signing_key_file",
        environment_names=("OPENZYME_REPOSITORY_CREDENTIAL_SIGNING_KEY_FILE",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.tls_certificate_file",
        environment_names=("OPENZYME_REPOSITORY_TLS_CERTIFICATE_FILE",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.tls_private_key_file",
        environment_names=("OPENZYME_REPOSITORY_TLS_PRIVATE_KEY_FILE",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.binding_inventory_file",
        environment_names=("OPENZYME_REPOSITORY_BINDING_INVENTORY_FILE",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.git_executable",
        environment_names=("OPENZYME_REPOSITORY_GIT_EXECUTABLE",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.git_lfs_executable",
        environment_names=("OPENZYME_REPOSITORY_GIT_LFS_EXECUTABLE",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.git_http_backend",
        environment_names=("OPENZYME_REPOSITORY_GIT_HTTP_BACKEND",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="repository_service.credential_ttl_seconds",
        environment_names=("OPENZYME_REPOSITORY_CREDENTIAL_TTL_SECONDS",),
        value_kind="integer",
        safe_generic_default=300,
    ),
    EnvironmentFieldDescriptor(
        setting_path="agent_capsule.deployment_network",
        environment_names=("OPENZYME_AGENT_CAPSULE_DEPLOYMENT_NETWORK",),
        value_kind="string",
        safe_generic_default=None,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="agent_capsule.podman_binary",
        environment_names=("OPENZYME_AGENT_CAPSULE_PODMAN_BINARY",),
        value_kind="private_string",
        safe_generic_default=None,
        identity_mode="private_digest",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="v3_background_runtime.enabled",
        environment_names=("OPENZYME_V3_BACKGROUND_RUNTIME_ENABLED",),
        value_kind="boolean",
        safe_generic_default=True,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="v3_background_runtime.poll_interval_seconds",
        environment_names=("OPENZYME_V3_BACKGROUND_RUNTIME_POLL_INTERVAL_SECONDS",),
        value_kind="number",
        safe_generic_default=2.0,
    ),
    EnvironmentFieldDescriptor(
        setting_path="v3_background_runtime.max_signals_per_tick",
        environment_names=("OPENZYME_V3_BACKGROUND_RUNTIME_MAX_SIGNALS_PER_TICK",),
        value_kind="integer",
        safe_generic_default=3,
    ),
    EnvironmentFieldDescriptor(
        setting_path="v3_background_runtime.max_steps_per_agent",
        environment_names=("OPENZYME_V3_BACKGROUND_RUNTIME_MAX_STEPS_PER_AGENT",),
        value_kind="integer",
        safe_generic_default=12,
    ),
    EnvironmentFieldDescriptor(
        setting_path="v3_background_runtime.shutdown_timeout_seconds",
        environment_names=("OPENZYME_V3_BACKGROUND_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS",),
        value_kind="number",
        safe_generic_default=10.0,
    ),
    EnvironmentFieldDescriptor(
        setting_path="execution.backend",
        environment_names=("OPENZYME_EXECUTION_BACKEND",),
        value_kind="string",
        safe_generic_default="disabled",
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="execution.hpc_runner_config",
        environment_names=("OPENZYME_HPC_RUNNER_CONFIG", "HPC_RUNNER_CONFIG"),
        value_kind="path",
        safe_generic_default=None,
        identity_mode="path_identity",
    ),
    EnvironmentFieldDescriptor(
        setting_path="execution.hpc_credential_provider_id",
        environment_names=("OPENZYME_HPC_CREDENTIAL_PROVIDER_ID",),
        value_kind="string",
        safe_generic_default=None,
    ),
    EnvironmentFieldDescriptor(
        setting_path="execution.hpc_authenticator_id",
        environment_names=("OPENZYME_HPC_AUTHENTICATOR_ID",),
        value_kind="string",
        safe_generic_default=None,
    ),
    EnvironmentFieldDescriptor(
        setting_path="execution.hpc_credential_issue_command",
        environment_names=("OPENZYME_HPC_CREDENTIAL_ISSUE_COMMAND",),
        value_kind="string_list",
        safe_generic_default=[],
        identity_mode="private_digest",
    ),
    EnvironmentFieldDescriptor(
        setting_path="execution.hpc_credential_revoke_command",
        environment_names=("OPENZYME_HPC_CREDENTIAL_REVOKE_COMMAND",),
        value_kind="string_list",
        safe_generic_default=[],
        identity_mode="private_digest",
    ),
    EnvironmentFieldDescriptor(
        setting_path="execution.hpc_credential_timeout_seconds",
        environment_names=("OPENZYME_HPC_CREDENTIAL_TIMEOUT_SECONDS",),
        value_kind="integer",
        safe_generic_default=30,
    ),
    *(
        EnvironmentFieldDescriptor(
            setting_path=f"limits.provider_limits.{name}",
            environment_names=(LIMIT_ENV_VARS[name],),
            value_kind="integer",
            safe_generic_default=default,
        )
        for name, default in sorted(DEFAULT_PROVIDER_LIMITS.items())
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.enable_live_llm",
        environment_names=("OPENZYME_TEST_ENABLE_LIVE_LLM",),
        value_kind="boolean",
        safe_generic_default=False,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.enable_live_tavily",
        environment_names=("OPENZYME_TEST_ENABLE_LIVE_TAVILY",),
        value_kind="boolean",
        safe_generic_default=False,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.enable_live_hpc",
        environment_names=("OPENZYME_TEST_ENABLE_LIVE_HPC",),
        value_kind="boolean",
        safe_generic_default=False,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.enable_live_e2e",
        environment_names=("OPENZYME_TEST_ENABLE_LIVE_E2E",),
        value_kind="boolean",
        safe_generic_default=False,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.enable_quality_eval",
        environment_names=("OPENZYME_TEST_ENABLE_QUALITY_EVAL",),
        value_kind="boolean",
        safe_generic_default=False,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.upload_langsmith",
        environment_names=("OPENZYME_TEST_UPLOAD_LANGSMITH",),
        value_kind="boolean",
        safe_generic_default=False,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.live_llm.max_tokens",
        environment_names=("OPENZYME_TEST_LIVE_LLM_MAX_TOKENS",),
        value_kind="optional_integer",
        safe_generic_default=None,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.live_llm.timeout",
        environment_names=("OPENZYME_TEST_LIVE_LLM_TIMEOUT",),
        value_kind="optional_number",
        safe_generic_default=None,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.live_llm.max_retries",
        environment_names=("OPENZYME_TEST_LIVE_LLM_MAX_RETRIES",),
        value_kind="optional_integer",
        safe_generic_default=None,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.live_llm.structured_output_method",
        environment_names=("OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_METHOD",),
        value_kind="string",
        safe_generic_default=None,
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.live_llm.structured_output_retry_backoff_seconds",
        environment_names=(
            "OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS",
        ),
        value_kind="optional_number",
        safe_generic_default=None,
        empty_uses_fallback=False,
    ),
    EnvironmentFieldDescriptor(
        setting_path="test.live_llm.token_ledger_path",
        environment_names=(LIVE_MICU_TOKEN_LEDGER_PATH_ENV,),
        value_kind="path",
        safe_generic_default=str(DEFAULT_LIVE_MICU_TOKEN_LEDGER_RELATIVE_PATH),
        identity_mode="path_identity",
    ),
    *reliability_environment_fields(),
)
_OPENZYME_SETTINGS_ENVIRONMENT_FIELD_MAP = field_map(
    _OPENZYME_SETTINGS_ENVIRONMENT_FIELDS
)


def openzyme_settings_environment_fields() -> tuple[EnvironmentFieldDescriptor, ...]:
    """Return the exact environment descriptors consumed by the AOX profile."""

    return _OPENZYME_SETTINGS_ENVIRONMENT_FIELDS


def openzyme_settings_environment_contract() -> list[dict[str, object]]:
    return [
        field.public_metadata()
        for field in sorted(
            _OPENZYME_SETTINGS_ENVIRONMENT_FIELDS,
            key=lambda item: item.setting_path,
        )
    ]


def openzyme_settings_source_projection(
    environ: Mapping[str, str],
) -> dict[str, object]:
    return credential_safe_source_projection(
        tuple(
            field
            for field in _OPENZYME_SETTINGS_ENVIRONMENT_FIELDS
            if field.candidate_identity
        ),
        environ,
    )


def resolve_openzyme_settings_environment_field(
    setting_path: str,
    environ: Mapping[str, str],
) -> object:
    return _OPENZYME_SETTINGS_ENVIRONMENT_FIELD_MAP[setting_path].resolve(environ)


def _environment_field(
    setting_path: str,
    environ: Mapping[str, str],
) -> object:
    return resolve_openzyme_settings_environment_field(setting_path, environ)


def _default_llm_extra_body(*, model: str, base_url: str) -> dict[str, Any] | None:
    if "open.bigmodel.cn" in base_url or model.startswith("glm-"):
        return dict(_BIGMODEL_EXTRA_BODY)
    return None


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def load_env_files(file_names: tuple[str, ...] = DEFAULT_ENV_FILES) -> None:
    original_env_keys = set(os.environ)
    loaded_values: dict[str, str] = {}
    for file_name in file_names:
        path = REPO_ROOT / file_name
        if not path.exists():
            continue
        for key, value in _parse_env_file(path).items():
            if key in original_env_keys:
                continue
            loaded_values[key] = value
    os.environ.update(loaded_values)


@dataclass(frozen=True, slots=True)
class ResolvedLlmPolicy:
    max_tokens: int | None
    timeout: float | None
    max_retries: int
    structured_output_method: str
    structured_output_retry_backoff_seconds: float


@dataclass(frozen=True, slots=True)
class LlmPurposePolicy:
    max_tokens: int | None = None
    timeout: float | None = None
    max_retries: int | None = None
    structured_output_method: str | None = None
    structured_output_retry_backoff_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class LlmSettings:
    api_key: str | None = field(repr=False)
    model: str
    base_url: str
    extra_body: dict[str, Any] | None = field(repr=False)
    default_headers: dict[str, str] | None = field(repr=False)
    use_responses_api: bool
    max_tokens: int | None
    timeout: float | None
    max_retries: int
    temperature: float
    structured_output_method: str
    structured_output_retry_backoff_seconds: float
    purpose_policies: dict[str, LlmPurposePolicy]
    context_window_tokens: int | None = None
    default_output_tokens: int | None = None
    context_warn_ratio: float = 0.80
    context_auto_compact_ratio: float = 0.85
    context_emergency_ratio: float = 0.90
    tokenizer_enabled: bool = False

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def policy_for_purpose(self, purpose: str | None) -> ResolvedLlmPolicy:
        override = self.purpose_policies.get(purpose or "", LlmPurposePolicy())
        return ResolvedLlmPolicy(
            max_tokens=self.max_tokens
            if override.max_tokens is None
            else override.max_tokens,
            timeout=self.timeout if override.timeout is None else override.timeout,
            max_retries=self.max_retries
            if override.max_retries is None
            else override.max_retries,
            structured_output_method=(
                self.structured_output_method
                if override.structured_output_method is None
                else override.structured_output_method
            ),
            structured_output_retry_backoff_seconds=(
                self.structured_output_retry_backoff_seconds
                if override.structured_output_retry_backoff_seconds is None
                else override.structured_output_retry_backoff_seconds
            ),
        )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "LlmSettings":
        source = os.environ if environ is None else environ
        user_agent_value = _environment_field("llm.default_headers", source)
        user_agent = str(user_agent_value).strip() or None
        api_key_value = _environment_field("llm.api_key", source)
        api_key = None if api_key_value is None else str(api_key_value)
        model = str(_environment_field("llm.model", source))
        base_url = str(_environment_field("llm.base_url", source))
        extra_body_value = _environment_field("llm.extra_body", source)
        extra_body = None if extra_body_value is None else dict(extra_body_value)
        if extra_body is None:
            extra_body = _default_llm_extra_body(model=model, base_url=base_url)
        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            extra_body=extra_body,
            default_headers={"User-Agent": user_agent}
            if user_agent is not None
            else None,
            use_responses_api=bool(_environment_field("llm.use_responses_api", source)),
            max_tokens=_optional_int_value(
                _environment_field("llm.max_tokens", source)
            ),
            timeout=_optional_float_value(_environment_field("llm.timeout", source)),
            max_retries=int(_environment_field("llm.max_retries", source)),
            temperature=float(_environment_field("llm.temperature", source)),
            structured_output_method=str(
                _environment_field("llm.structured_output_method", source)
            ),
            structured_output_retry_backoff_seconds=float(
                _environment_field(
                    "llm.structured_output_retry_backoff_seconds",
                    source,
                )
            ),
            purpose_policies=_load_llm_purpose_policies(source),
            context_window_tokens=_optional_int_value(
                _environment_field("llm.context_window_tokens", source)
            ),
            default_output_tokens=_optional_int_value(
                _environment_field("llm.default_output_tokens", source)
            ),
            context_warn_ratio=float(
                _environment_field("llm.context_warn_ratio", source)
            ),
            context_auto_compact_ratio=float(
                _environment_field("llm.context_auto_compact_ratio", source)
            ),
            context_emergency_ratio=float(
                _environment_field("llm.context_emergency_ratio", source)
            ),
            tokenizer_enabled=bool(_environment_field("llm.tokenizer_enabled", source)),
        )


def _optional_int_value(value: object) -> int | None:
    return None if value is None else int(value)


def _optional_float_value(value: object) -> float | None:
    return None if value is None else float(value)


def _optional_string_value(value: object) -> str | None:
    return None if value is None else str(value)


def _load_llm_purpose_policies(
    environ: Mapping[str, str],
) -> dict[str, LlmPurposePolicy]:
    policies: dict[str, LlmPurposePolicy] = {}
    for purpose in LLM_PURPOSES:
        prefix = f"llm.purpose_policies.{purpose}"
        policy = LlmPurposePolicy(
            max_tokens=_optional_int_value(
                _environment_field(f"{prefix}.max_tokens", environ)
            ),
            timeout=_optional_float_value(
                _environment_field(f"{prefix}.timeout", environ)
            ),
            max_retries=_optional_int_value(
                _environment_field(f"{prefix}.max_retries", environ)
            ),
            structured_output_method=_optional_string_value(
                _environment_field(f"{prefix}.structured_output_method", environ)
            ),
            structured_output_retry_backoff_seconds=_optional_float_value(
                _environment_field(
                    f"{prefix}.structured_output_retry_backoff_seconds",
                    environ,
                )
            ),
        )
        if any(
            value is not None
            for value in (
                policy.timeout,
                policy.max_tokens,
                policy.max_retries,
                policy.structured_output_method,
                policy.structured_output_retry_backoff_seconds,
            )
        ):
            policies[purpose] = policy
    return policies


@dataclass(frozen=True, slots=True)
class ResearchSettings:
    max_units: int
    allow_clarification: bool
    max_research_iterations: int
    max_react_tool_calls: int
    max_concurrent_research_units: int
    tavily_api_key: str | None = field(repr=False)
    tavily_max_results: int
    tavily_topic: str
    mcp_tool_allowlist: tuple[str, ...] = ()
    tavily_timeout_seconds: float = 30.0
    pubmed_email: str | None = field(default=None, repr=False)
    pubmed_tool: str = "openzyme"
    pubmed_api_key: str | None = field(default=None, repr=False)
    semantic_scholar_api_key: str | None = field(default=None, repr=False)
    provider_timeout_seconds: float = 30.0
    provider_max_attempts: int = 3

    @property
    def tavily_enabled(self) -> bool:
        return bool(self.tavily_api_key)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ResearchSettings":
        source = os.environ if environ is None else environ
        return cls(
            max_units=int(_environment_field("research.max_units", source)),
            allow_clarification=bool(
                _environment_field("research.allow_clarification", source)
            ),
            max_research_iterations=int(
                _environment_field("research.max_research_iterations", source)
            ),
            max_react_tool_calls=int(
                _environment_field("research.max_react_tool_calls", source)
            ),
            max_concurrent_research_units=int(
                _environment_field("research.max_concurrent_research_units", source)
            ),
            tavily_api_key=_optional_string_value(
                _environment_field("research.tavily_api_key", source)
            ),
            tavily_max_results=int(
                _environment_field("research.tavily_max_results", source)
            ),
            tavily_topic=str(_environment_field("research.tavily_topic", source)),
            mcp_tool_allowlist=tuple(
                _environment_field("research.mcp_tool_allowlist", source)
            ),
            tavily_timeout_seconds=float(
                _environment_field("research.tavily_timeout_seconds", source)
            ),
            pubmed_email=_optional_string_value(
                _environment_field("research.pubmed_email", source)
            ),
            pubmed_tool=str(_environment_field("research.pubmed_tool", source)),
            pubmed_api_key=_optional_string_value(
                _environment_field("research.pubmed_api_key", source)
            ),
            semantic_scholar_api_key=_optional_string_value(
                _environment_field("research.semantic_scholar_api_key", source)
            ),
            provider_timeout_seconds=float(
                _environment_field("research.provider_timeout_seconds", source)
            ),
            provider_max_attempts=int(
                _environment_field("research.provider_max_attempts", source)
            ),
        )


@dataclass(frozen=True, slots=True)
class TracingSettings:
    enabled: bool
    project_name: str

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "TracingSettings":
        source = os.environ if environ is None else environ
        return cls(
            enabled=bool(_environment_field("tracing.enabled", source)),
            project_name=str(_environment_field("tracing.project_name", source)),
        )


@dataclass(frozen=True, slots=True)
class HostCliSettings:
    base_url: str
    project_id: str | None
    output_format: str
    auth_token: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "HostCliSettings":
        source = os.environ if environ is None else environ
        return cls(
            base_url=str(_environment_field("host_cli.base_url", source)),
            project_id=_optional_string_value(
                _environment_field("host_cli.project_id", source)
            ),
            output_format=str(_environment_field("host_cli.output_format", source)),
            auth_token=_optional_string_value(
                _environment_field("host_cli.auth_token", source)
            ),
        )


@dataclass(frozen=True, slots=True)
class HostApiPrincipalSettings:
    principal_id: str
    token_sha256: str = field(repr=False)
    roles: frozenset[str]
    project_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class HostApiSettings:
    bind_host: str
    bind_port: int
    deployment_profile: str = HOST_API_LOCAL_DEPLOYMENT_PROFILE
    principals: tuple[HostApiPrincipalSettings, ...] = ()
    debug_enabled: bool = False

    def __post_init__(self) -> None:
        if self.deployment_profile not in HOST_API_DEPLOYMENT_PROFILES:
            raise ValueError(
                "OPENZYME_HOST_DEPLOYMENT_PROFILE must be 'local-dev' or 'shared'"
            )
        if (
            self.deployment_profile == HOST_API_LOCAL_DEPLOYMENT_PROFILE
            and self.bind_host not in HOST_API_LOOPBACK_BIND_HOSTS
        ):
            raise ValueError(
                "local-dev Host API must bind to a loopback address; use the "
                "shared profile for a remotely reachable service"
            )
        if self.deployment_profile == "shared" and not self.principals:
            raise ValueError(
                "shared Host API requires OPENZYME_HOST_AUTH_PRINCIPALS_JSON"
            )
        principal_ids = [item.principal_id for item in self.principals]
        token_digests = [item.token_sha256 for item in self.principals]
        if len(principal_ids) != len(set(principal_ids)):
            raise ValueError("Host API principal_id values must be unique")
        if len(token_digests) != len(set(token_digests)):
            raise ValueError("Host API bearer tokens must be unique")

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "HostApiSettings":
        source = os.environ if environ is None else environ
        return cls(
            bind_host=str(_environment_field("host_api.bind_host", source)),
            bind_port=int(_environment_field("host_api.bind_port", source)),
            deployment_profile=str(
                _environment_field("host_api.deployment_profile", source)
            ),
            principals=_parse_host_api_principals(
                _optional_string_value(
                    _environment_field("host_api.principals", source)
                )
            ),
            debug_enabled=bool(_environment_field("host_api.debug_enabled", source)),
        )


@dataclass(frozen=True, slots=True)
class RepositoryServiceSettings:
    https_origin: str
    bare_repository_root: Path
    lfs_object_root: Path
    backup_root: Path
    credential_signing_key_file: Path
    tls_certificate_file: Path
    tls_private_key_file: Path
    binding_inventory_file: Path
    git_executable: Path
    git_lfs_executable: Path
    git_http_backend: Path
    credential_ttl_seconds: int = 300

    def __post_init__(self) -> None:
        parsed = urlsplit(self.https_origin)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("OPENZYME_REPOSITORY_HTTPS_ORIGIN must be an HTTPS origin")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(
                "OPENZYME_REPOSITORY_HTTPS_ORIGIN must not embed credentials"
            )
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError(
                "OPENZYME_REPOSITORY_HTTPS_ORIGIN must not include path, query, or fragment"
            )
        for field_name in (
            "bare_repository_root",
            "lfs_object_root",
            "backup_root",
            "credential_signing_key_file",
            "tls_certificate_file",
            "tls_private_key_file",
            "binding_inventory_file",
            "git_executable",
            "git_lfs_executable",
            "git_http_backend",
        ):
            path = getattr(self, field_name)
            if not path.is_absolute():
                raise ValueError(f"repository service {field_name} must be absolute")
        if len(
            {
                self.bare_repository_root.resolve(strict=False),
                self.lfs_object_root.resolve(strict=False),
                self.backup_root.resolve(strict=False),
            }
        ) != 3:
            raise ValueError("repository Git, LFS, and backup roots must be distinct")
        if self.credential_ttl_seconds <= 0:
            raise ValueError(
                "OPENZYME_REPOSITORY_CREDENTIAL_TTL_SECONDS must be positive"
            )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "RepositoryServiceSettings | None":
        source = os.environ if environ is None else environ
        required_paths = {
            "https_origin": "repository_service.https_origin",
            "bare_repository_root": "repository_service.bare_repository_root",
            "lfs_object_root": "repository_service.lfs_object_root",
            "backup_root": "repository_service.backup_root",
            "credential_signing_key_file": (
                "repository_service.credential_signing_key_file"
            ),
            "tls_certificate_file": "repository_service.tls_certificate_file",
            "tls_private_key_file": "repository_service.tls_private_key_file",
            "binding_inventory_file": "repository_service.binding_inventory_file",
            "git_executable": "repository_service.git_executable",
            "git_lfs_executable": "repository_service.git_lfs_executable",
            "git_http_backend": "repository_service.git_http_backend",
        }
        resolved = {
            field_name: _optional_string_value(_environment_field(setting_path, source))
            for field_name, setting_path in required_paths.items()
        }
        configured = {name for name, value in resolved.items() if value is not None}
        if not configured:
            return None
        missing = sorted(set(resolved) - configured)
        if missing:
            raise ValueError(
                "repository service configuration is partial; missing: "
                + ", ".join(missing)
            )
        return cls(
            https_origin=str(resolved["https_origin"]),
            bare_repository_root=Path(str(resolved["bare_repository_root"])),
            lfs_object_root=Path(str(resolved["lfs_object_root"])),
            backup_root=Path(str(resolved["backup_root"])),
            credential_signing_key_file=Path(
                str(resolved["credential_signing_key_file"])
            ),
            tls_certificate_file=Path(str(resolved["tls_certificate_file"])),
            tls_private_key_file=Path(str(resolved["tls_private_key_file"])),
            binding_inventory_file=Path(str(resolved["binding_inventory_file"])),
            git_executable=Path(str(resolved["git_executable"])),
            git_lfs_executable=Path(str(resolved["git_lfs_executable"])),
            git_http_backend=Path(str(resolved["git_http_backend"])),
            credential_ttl_seconds=int(
                _environment_field("repository_service.credential_ttl_seconds", source)
            ),
        )


@dataclass(frozen=True, slots=True)
class AgentCapsuleSettings:
    deployment_network: str
    podman_binary: Path

    def __post_init__(self) -> None:
        if (
            not self.deployment_network
            or self.deployment_network.strip() != self.deployment_network
        ):
            raise ValueError(
                "OPENZYME_AGENT_CAPSULE_DEPLOYMENT_NETWORK must be a non-empty exact name"
            )
        if not self.podman_binary.is_absolute():
            raise ValueError(
                "OPENZYME_AGENT_CAPSULE_PODMAN_BINARY must be an absolute path"
            )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "AgentCapsuleSettings | None":
        source = os.environ if environ is None else environ
        deployment_network = _optional_string_value(
            _environment_field("agent_capsule.deployment_network", source)
        )
        podman_binary = _optional_string_value(
            _environment_field("agent_capsule.podman_binary", source)
        )
        configured = {
            name
            for name, value in {
                "deployment_network": deployment_network,
                "podman_binary": podman_binary,
            }.items()
            if value is not None
        }
        if not configured:
            return None
        missing = sorted({"deployment_network", "podman_binary"} - configured)
        if missing:
            raise ValueError(
                "agent capsule configuration is partial; missing: "
                + ", ".join(missing)
            )
        return cls(
            deployment_network=str(deployment_network),
            podman_binary=Path(str(podman_binary)),
        )


def _parse_host_api_principals(
    value: str | None,
) -> tuple[HostApiPrincipalSettings, ...]:
    if value in {None, ""}:
        return ()
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("OPENZYME_HOST_AUTH_PRINCIPALS_JSON must be a JSON array")
    principals: list[HostApiPrincipalSettings] = []
    valid_roles = {"user", "operator", "admin"}
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise ValueError(f"Host API principal at index {index} must be an object")
        principal_id = str(item.get("principal_id") or "").strip()
        token = str(item.get("token") or "")
        roles_raw = item.get("roles")
        projects_raw = item.get("project_ids")
        if len(principal_id) <= len("user:") or not principal_id.startswith("user:"):
            raise ValueError(
                "Host API principal_id must be non-empty and start with 'user:'"
            )
        if len(token) < 32:
            raise ValueError(
                "Host API bearer tokens must contain at least 32 characters"
            )
        if token != token.strip() or any(char.isspace() for char in token):
            raise ValueError("Host API bearer tokens cannot contain whitespace")
        if not isinstance(roles_raw, list) or not roles_raw:
            raise ValueError("Host API principal roles must be a non-empty array")
        if not isinstance(projects_raw, list) or not projects_raw:
            raise ValueError("Host API principal project_ids must be a non-empty array")
        roles = frozenset(str(role).strip() for role in roles_raw)
        project_ids = frozenset(str(project_id).strip() for project_id in projects_raw)
        if not roles <= valid_roles:
            raise ValueError(
                f"unsupported Host API principal role: {sorted(roles - valid_roles)[0]}"
            )
        if "" in project_ids:
            raise ValueError(
                "Host API principal project_ids cannot contain empty values"
            )
        principals.append(
            HostApiPrincipalSettings(
                principal_id=principal_id,
                token_sha256=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                roles=roles,
                project_ids=project_ids,
            )
        )
    return tuple(principals)


@dataclass(frozen=True, slots=True)
class V3BackgroundRuntimeSettings:
    enabled: bool
    poll_interval_seconds: float
    max_signals_per_tick: int
    max_steps_per_agent: int
    shutdown_timeout_seconds: float

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "V3BackgroundRuntimeSettings":
        source = os.environ if environ is None else environ
        max_signals_per_tick = int(
            _environment_field(
                "v3_background_runtime.max_signals_per_tick",
                source,
            )
        )
        max_steps_per_agent = int(
            _environment_field(
                "v3_background_runtime.max_steps_per_agent",
                source,
            )
        )
        if max_signals_per_tick <= 0:
            raise ValueError(
                "OPENZYME_V3_BACKGROUND_RUNTIME_MAX_SIGNALS_PER_TICK must be positive"
            )
        if max_steps_per_agent <= 0:
            raise ValueError(
                "OPENZYME_V3_BACKGROUND_RUNTIME_MAX_STEPS_PER_AGENT must be positive"
            )
        poll_interval_seconds = float(
            _environment_field(
                "v3_background_runtime.poll_interval_seconds",
                source,
            )
        )
        shutdown_timeout_seconds = float(
            _environment_field(
                "v3_background_runtime.shutdown_timeout_seconds",
                source,
            )
        )
        if poll_interval_seconds <= 0:
            raise ValueError(
                "OPENZYME_V3_BACKGROUND_RUNTIME_POLL_INTERVAL_SECONDS must be positive"
            )
        if shutdown_timeout_seconds <= 0:
            raise ValueError(
                "OPENZYME_V3_BACKGROUND_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS must be positive"
            )
        return cls(
            enabled=bool(_environment_field("v3_background_runtime.enabled", source)),
            poll_interval_seconds=poll_interval_seconds,
            max_signals_per_tick=max_signals_per_tick,
            max_steps_per_agent=max_steps_per_agent,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class ExecutionSettings:
    backend: str
    hpc_runner_config: str | None
    hpc_credential_provider_id: str | None = None
    hpc_authenticator_id: str | None = None
    hpc_credential_issue_command: tuple[str, ...] = ()
    hpc_credential_revoke_command: tuple[str, ...] = ()
    hpc_credential_timeout_seconds: int = 30

    def __post_init__(self) -> None:
        credential_values = (
            self.hpc_credential_provider_id,
            self.hpc_authenticator_id,
            self.hpc_credential_issue_command or None,
            self.hpc_credential_revoke_command or None,
        )
        if any(value is not None for value in credential_values) and any(
            value is None for value in credential_values
        ):
            raise ValueError(
                "HPC credential provider id, authenticator id, issue command, "
                "and revoke command must be configured together"
            )
        for command in (
            self.hpc_credential_issue_command,
            self.hpc_credential_revoke_command,
        ):
            if command and not Path(command[0]).is_absolute():
                raise ValueError("HPC credential commands require absolute executables")
        if not 1 <= self.hpc_credential_timeout_seconds <= 300:
            raise ValueError(
                "HPC credential command timeout must be between 1 and 300 seconds"
            )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ExecutionSettings":
        source = os.environ if environ is None else environ
        return cls(
            backend=str(_environment_field("execution.backend", source)),
            hpc_runner_config=_optional_string_value(
                _environment_field("execution.hpc_runner_config", source)
            ),
            hpc_credential_provider_id=_optional_string_value(
                _environment_field("execution.hpc_credential_provider_id", source)
            ),
            hpc_authenticator_id=_optional_string_value(
                _environment_field("execution.hpc_authenticator_id", source)
            ),
            hpc_credential_issue_command=tuple(
                str(value)
                for value in _environment_field(
                    "execution.hpc_credential_issue_command",
                    source,
                )
            ),
            hpc_credential_revoke_command=tuple(
                str(value)
                for value in _environment_field(
                    "execution.hpc_credential_revoke_command",
                    source,
                )
            ),
            hpc_credential_timeout_seconds=int(
                _environment_field(
                    "execution.hpc_credential_timeout_seconds",
                    source,
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class LimiterSettings:
    provider_limits: dict[str, int]

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "LimiterSettings":
        source = os.environ if environ is None else environ
        limits: dict[str, int] = {}
        for name in DEFAULT_PROVIDER_LIMITS:
            value = int(_environment_field(f"limits.provider_limits.{name}", source))
            if value <= 0:
                raise ValueError(f"{LIMIT_ENV_VARS[name]} must be positive")
            limits[name] = value
        return cls(provider_limits=limits)


def _default_limiter_settings() -> LimiterSettings:
    return LimiterSettings(provider_limits=dict(DEFAULT_PROVIDER_LIMITS))


@dataclass(frozen=True, slots=True)
class LiveLlmTestSettings:
    max_tokens: int | None
    timeout: float | None
    max_retries: int | None
    structured_output_method: str | None
    structured_output_retry_backoff_seconds: float | None
    token_ledger_path: str = str(DEFAULT_LIVE_MICU_TOKEN_LEDGER_PATH)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "LiveLlmTestSettings":
        source = os.environ if environ is None else environ
        configured_ledger = _optional_string_value(
            _environment_field("test.live_llm.token_ledger_path", source)
        )
        return cls(
            max_tokens=_optional_int_value(
                _environment_field("test.live_llm.max_tokens", source)
            ),
            timeout=_optional_float_value(
                _environment_field("test.live_llm.timeout", source)
            ),
            max_retries=_optional_int_value(
                _environment_field("test.live_llm.max_retries", source)
            ),
            structured_output_method=_optional_string_value(
                _environment_field(
                    "test.live_llm.structured_output_method",
                    source,
                )
            ),
            structured_output_retry_backoff_seconds=_optional_float_value(
                _environment_field(
                    "test.live_llm.structured_output_retry_backoff_seconds",
                    source,
                )
            ),
            token_ledger_path=str(
                resolve_live_micu_token_ledger_path(configured_ledger)
            ),
        )


@dataclass(frozen=True, slots=True)
class TestSettings:
    enable_live_llm: bool
    enable_live_tavily: bool
    enable_live_hpc: bool
    enable_live_e2e: bool
    enable_quality_eval: bool
    upload_langsmith: bool
    live_llm: LiveLlmTestSettings

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "TestSettings":
        source = os.environ if environ is None else environ
        return cls(
            enable_live_llm=bool(_environment_field("test.enable_live_llm", source)),
            enable_live_tavily=bool(
                _environment_field("test.enable_live_tavily", source)
            ),
            enable_live_hpc=bool(_environment_field("test.enable_live_hpc", source)),
            enable_live_e2e=bool(_environment_field("test.enable_live_e2e", source)),
            enable_quality_eval=bool(
                _environment_field("test.enable_quality_eval", source)
            ),
            upload_langsmith=bool(_environment_field("test.upload_langsmith", source)),
            live_llm=LiveLlmTestSettings.from_env(source),
        )


@dataclass(frozen=True, slots=True)
class OpenZymeSettings:
    llm: LlmSettings
    research: ResearchSettings
    tracing: TracingSettings
    host_cli: HostCliSettings
    host_api: HostApiSettings
    v3_background_runtime: V3BackgroundRuntimeSettings
    execution: ExecutionSettings
    test: TestSettings
    limits: LimiterSettings = field(default_factory=_default_limiter_settings)
    reliability: ReliabilityRefactorSettings = field(
        default_factory=ReliabilityRefactorSettings
    )
    repository_service: RepositoryServiceSettings | None = None
    agent_capsule: AgentCapsuleSettings | None = None

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "OpenZymeSettings":
        if environ is None:
            load_env_files()
            source = os.environ
        else:
            source = environ
        return cls(
            llm=LlmSettings.from_env(source),
            research=ResearchSettings.from_env(source),
            tracing=TracingSettings.from_env(source),
            host_cli=HostCliSettings.from_env(source),
            host_api=HostApiSettings.from_env(source),
            v3_background_runtime=V3BackgroundRuntimeSettings.from_env(source),
            execution=ExecutionSettings.from_env(source),
            limits=LimiterSettings.from_env(source),
            test=TestSettings.from_env(source),
            reliability=ReliabilityRefactorSettings.from_env(source),
            repository_service=RepositoryServiceSettings.from_env(source),
            agent_capsule=AgentCapsuleSettings.from_env(source),
        )


@lru_cache(maxsize=1)
def get_settings() -> OpenZymeSettings:
    return OpenZymeSettings.from_env()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


__all__ = [
    "AgentCapsuleSettings",
    "DEFAULT_HOST_BASE_URL",
    "DEFAULT_HOST_API_BIND_HOST",
    "DEFAULT_HOST_API_BIND_PORT",
    "DEFAULT_LLM_STRUCTURED_OUTPUT_METHOD",
    "DEFAULT_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS",
    "DEFAULT_OPENAI_COMPAT_BASE_URL",
    "DEFAULT_OPENAI_COMPAT_EXTRA_BODY",
    "DEFAULT_OPENAI_COMPAT_MODEL",
    "DEFAULT_OPENAI_COMPAT_USER_AGENT",
    "DEFAULT_OPENAI_COMPAT_USE_RESPONSES_API",
    "ExecutionSettings",
    "HOST_API_DEPLOYMENT_PROFILES",
    "HOST_API_LOCAL_DEPLOYMENT_PROFILE",
    "HOST_API_LOOPBACK_BIND_HOSTS",
    "HostApiSettings",
    "HostApiPrincipalSettings",
    "HostCliSettings",
    "LiveLlmTestSettings",
    "LimiterSettings",
    "LlmPurposePolicy",
    "LlmSettings",
    "OpenZymeSettings",
    "REPO_ROOT",
    "ResolvedLlmPolicy",
    "ResearchSettings",
    "RepositoryServiceSettings",
    "ReliabilityRefactorSettings",
    "TracingSettings",
    "V3BackgroundRuntimeSettings",
    "get_settings",
    "load_env_files",
    "openzyme_settings_environment_contract",
    "openzyme_settings_environment_fields",
    "openzyme_settings_source_projection",
    "resolve_openzyme_settings_environment_field",
    "reset_settings_cache",
]
