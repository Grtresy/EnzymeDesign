"""Explicit LLM/provider Adapter with a locator-safe import boundary."""

from __future__ import annotations

from importlib import import_module
from typing import Any


COMPONENT_ID = "openzyme.runtime.llm"
COMPONENT_KIND = "adapter"
MIGRATION_STATE = "target_implemented_legacy_callers_pending"

_EXPORT_MODULES = {
    "LLM_ADAPTER_PREFLIGHT_CONTRACT": "adapter",
    "LLM_ADAPTER_PREFLIGHT_CONTRACT_DIGEST": "adapter",
    "LLM_RUNTIME_ADAPTER_CONTRACT": "adapter",
    "LLM_RUNTIME_ADAPTER_CONTRACT_DIGEST": "adapter",
    "LLM_RUNTIME_ADAPTER_ID": "adapter",
    "LlmAdapterPreflight": "adapter",
    "LlmRuntimeAdapter": "adapter",
    "LLM_ADAPTER_CONFIGURATION_SCHEMA": "configuration",
    "LLM_ADAPTER_CONFIGURATION_SCHEMA_DIGEST": "configuration",
    "LlmAdapterConfiguration": "configuration",
    "LlmConnectivityConfigurationError": "connectivity",
    "LlmConnectivityRequest": "connectivity",
    "run_connectivity_check": "connectivity",
    "LangChainProviderBackend": "provider",
    "LLM_PROVIDER_BACKEND_CONTRACT": "provider",
    "LLM_PROVIDER_BACKEND_CONTRACT_DIGEST": "provider",
    "LlmProviderBackend": "provider",
    "LlmProviderError": "provider",
    "ProviderToolCall": "provider",
    "ProviderTurnRequest": "provider",
    "ProviderTurnResponse": "provider",
    "ChatModelFactory": "ai",
    "LangChainModelFactory": "ai",
    "LangChainStructuredInvoker": "ai",
    "LangChainToolCallingInvoker": "ai",
    "LimitedStructuredOutputInvoker": "ai",
    "LimitedToolCallingInvoker": "ai",
    "MissingLangChainDependencyError": "ai",
    "MissingLangChainProviderDependencyError": "ai",
    "MissingLlmConfigurationError": "ai",
    "OpenAICompatibleChatModelFactory": "ai",
    "StructuredOutputInvoker": "ai",
    "ToolCallingInvoker": "ai",
    "AsyncConcurrencyLimiter": "limits",
    "DEFAULT_PROVIDER_LIMITS": "limits",
    "LimiterRegistry": "limits",
    "SyncConcurrencyLimiter": "limits",
    "DEFAULT_LIVE_MICU_TOKEN_LEDGER_PATH": "live_token_ledger",
    "DEFAULT_LIVE_MICU_TOKEN_LEDGER_RELATIVE_PATH": "live_token_ledger",
    "LIVE_MICU_TOKEN_HARD_LIMIT": "live_token_ledger",
    "LiveMicuTokenBudgetExceededError": "live_token_ledger",
    "LiveMicuTokenLedger": "live_token_ledger",
    "LiveMicuTokenPolicyMigrationError": "live_token_ledger",
    "LiveMicuTokenReservation": "live_token_ledger",
    "LiveMicuTokenReservationConfigurationError": "live_token_ledger",
    "configured_live_micu_token_ledger_path": "live_token_ledger",
    "estimate_llm_request_tokens": "live_token_ledger",
    "is_micu_provider_url": "live_token_ledger",
    "migrate_legacy_live_micu_token_policy": "live_token_ledger",
    "resolve_live_micu_token_ledger_path": "live_token_ledger",
    "summarize_live_micu_token_ledger": "live_token_ledger",
    "classify_llm_provider_error": "llm_invocation",
    "extract_llm_usage": "llm_invocation",
    "is_retryable_llm_provider_error": "llm_invocation",
    "LlmInvocationRuntime": "llm_invocation",
    "LlmProviderErrorClassification": "llm_invocation",
    "LlmProviderInvocationError": "llm_invocation",
    "max_attempts_from_retries": "llm_invocation",
    "LlmDebugRecorder": "llm_debug",
    "current_llm_debug_context": "llm_debug",
    "get_llm_debug_recorder": "llm_debug",
    "llm_debug_context": "llm_debug",
    "serialize_llm_payload": "llm_debug",
    "openai_tool_from_spec": "provider_tools",
    "ProviderToolAdapter": "provider_tools",
    "ProviderToolCatalog": "provider_tools",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORT_MODULES})


__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    *_EXPORT_MODULES,
]
