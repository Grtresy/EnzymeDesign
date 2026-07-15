from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Protocol
from typing import TypeVar

from pydantic import BaseModel

from .limits import LimiterRegistry
from .llm_invocation import is_retryable_llm_provider_error
from .llm_invocation import LlmInvocationRuntime
from .llm_invocation import max_attempts_from_retries
from .llm_debug import serialize_llm_payload
from .provider_tools import ProviderToolAdapter


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class MissingLangChainDependencyError(RuntimeError):
    """Raised when LangChain is required but not installed."""


class MissingLangChainProviderDependencyError(RuntimeError):
    """Raised when the configured LangChain provider package is unavailable."""


class MissingLlmConfigurationError(RuntimeError):
    """Raised when no model configuration is available for LangChain inference."""


class StructuredOutputInvoker(Protocol):
    def invoke_structured(
        self,
        *,
        schema: type[SchemaT],
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> SchemaT: ...


class ToolCallingInvoker(Protocol):
    def invoke_with_tools(
        self,
        *,
        system_prompt: str,
        messages: list[Any],
        tools: list[Any],
    ) -> Any: ...


class ChatModelFactory(Protocol):
    def create_structured_invoker(self, *, purpose: str) -> StructuredOutputInvoker: ...

    def create_tool_calling_invoker(self, *, purpose: str) -> ToolCallingInvoker: ...


@dataclass(frozen=True, slots=True)
class LimitedStructuredOutputInvoker:
    invoker: StructuredOutputInvoker
    limiter_registry: LimiterRegistry
    limiter_name: str = "llm_provider"

    def invoke_structured(
        self,
        *,
        schema: type[SchemaT],
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> SchemaT:
        return self.limiter_registry.sync_limiter(self.limiter_name).run(
            lambda: self.invoker.invoke_structured(
                schema=schema,
                system_prompt=system_prompt,
                user_payload=user_payload,
            )
        )


@dataclass(frozen=True, slots=True)
class LimitedToolCallingInvoker:
    invoker: ToolCallingInvoker
    limiter_registry: LimiterRegistry
    limiter_name: str = "llm_provider"

    def invoke_with_tools(
        self,
        *,
        system_prompt: str,
        messages: list[Any],
        tools: list[Any],
    ) -> Any:
        return self.limiter_registry.sync_limiter(self.limiter_name).run(
            lambda: self.invoker.invoke_with_tools(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
            )
        )


@dataclass(frozen=True, slots=True)
class LangChainStructuredInvoker:
    model: Any
    purpose: str = "structured_output"
    model_name: str | None = None
    base_url: str | None = None
    diagnostic_label: str | None = None
    structured_output_method: str = "json_schema"
    max_attempts: int = 1
    retry_backoff_seconds: float = 1.0
    invocation_timeout_seconds: float | None = None
    limiter_registry: LimiterRegistry | None = None

    def invoke_structured(
        self,
        *,
        schema: type[SchemaT],
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> SchemaT:
        try:
            from langchain_core.messages import HumanMessage
            from langchain_core.messages import SystemMessage
        except ImportError as exc:  # pragma: no cover - exercised only in environments missing LangChain
            raise MissingLangChainDependencyError(
                "Install langchain to invoke structured model calls."
            ) from exc

        structured_model = self.model.with_structured_output(
            schema,
            method=self.structured_output_method,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=json.dumps(
                    user_payload,
                    ensure_ascii=True,
                    sort_keys=True,
                    default=str,
                )
            ),
        ]
        self._log_stage(f"LLM structured start purpose={self.purpose!r}")
        started = time.monotonic()
        raw_response: Any | None = None

        def invoke_and_parse() -> SchemaT:
            nonlocal raw_response
            raw_response = structured_model.invoke(messages)
            if isinstance(raw_response, schema):
                return raw_response
            return schema.model_validate(
                raw_response.model_dump()
                if isinstance(raw_response, BaseModel)
                else raw_response
            )

        parsed = self._runtime("structured").invoke(
            request={
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "schema": schema.model_json_schema(),
                "structured_output_method": self.structured_output_method,
                "messages": serialize_llm_payload(messages),
            },
            call=invoke_and_parse,
            phase=f"invoking LLM structured purpose={self.purpose!r}",
            debug_response=lambda response: {
                "raw": serialize_llm_payload(raw_response),
                "parsed": response.model_dump()
                if isinstance(response, BaseModel)
                else serialize_llm_payload(response),
            },
        )
        self._log_stage(
            f"LLM structured finished elapsed={time.monotonic() - started:.2f}s"
        )
        return parsed

    def _log_stage(self, message: str) -> None:
        if self.diagnostic_label is None:
            return
        print(f"[{self.diagnostic_label}] {message}", flush=True)

    def _runtime(self, kind: str) -> LlmInvocationRuntime:
        return LlmInvocationRuntime(
            purpose=self.purpose,
            kind=kind,
            model=self.model_name,
            base_url=self.base_url,
            max_attempts=self.max_attempts,
            retry_backoff_seconds=self.retry_backoff_seconds,
            invocation_timeout_seconds=self.invocation_timeout_seconds,
            diagnostic_label=self.diagnostic_label,
            limiter_registry=self.limiter_registry,
        )


@dataclass(frozen=True, slots=True)
class LangChainToolCallingInvoker:
    model: Any
    purpose: str = "tool_calling"
    model_name: str | None = None
    base_url: str | None = None
    diagnostic_label: str | None = None
    invocation_timeout_seconds: float | None = None
    max_attempts: int = 1
    retry_backoff_seconds: float = 1.0
    limiter_registry: LimiterRegistry | None = None
    dotted_tool_name_aliasing: bool = False

    def invoke_with_tools(
        self,
        *,
        system_prompt: str,
        messages: list[Any],
        tools: list[Any],
    ) -> Any:
        try:
            from langchain_core.messages import SystemMessage
        except ImportError as exc:  # pragma: no cover - exercised only in environments missing LangChain
            raise MissingLangChainDependencyError(
                "Install langchain to invoke tool-calling model calls."
            ) from exc
        provider_catalog = ProviderToolAdapter(
            dotted_tool_name_aliasing=self.dotted_tool_name_aliasing
        ).prepare(tools)
        provider_messages = provider_catalog.provider_messages(messages)
        runnable = self.model.bind_tools(provider_catalog.provider_tools)
        request_messages = [SystemMessage(content=system_prompt), *provider_messages]
        request: dict[str, Any] = {
            "system_prompt": system_prompt,
            "messages": serialize_llm_payload(provider_messages),
            "tools": provider_catalog.provider_tools,
            "canonical_to_provider": provider_catalog.canonical_to_provider,
            "provider_to_canonical": provider_catalog.provider_to_canonical,
            "request_messages": serialize_llm_payload(request_messages),
        }
        if provider_catalog.aliases:
            request["internal_messages"] = serialize_llm_payload(messages)
            request["internal_tools"] = tools
            request["tool_name_aliases"] = provider_catalog.aliases
        self._log_stage(f"LLM tool-calling start purpose={self.purpose!r}")
        started = time.monotonic()
        response = self._runtime("tool_calling").invoke(
            request=request,
            call=lambda: provider_catalog.restore_response(
                runnable.invoke(request_messages)
            ),
            phase=f"invoking LLM tool-calling purpose={self.purpose!r}",
        )
        self._log_stage(
            f"LLM tool-calling finished elapsed={time.monotonic() - started:.2f}s"
        )
        return response

    def _log_stage(self, message: str) -> None:
        if self.diagnostic_label is None:
            return
        print(f"[{self.diagnostic_label}] {message}", flush=True)

    def _runtime(self, kind: str) -> LlmInvocationRuntime:
        return LlmInvocationRuntime(
            purpose=self.purpose,
            kind=kind,
            model=self.model_name,
            base_url=self.base_url,
            max_attempts=self.max_attempts,
            retry_backoff_seconds=self.retry_backoff_seconds,
            invocation_timeout_seconds=self.invocation_timeout_seconds,
            diagnostic_label=self.diagnostic_label,
            limiter_registry=self.limiter_registry,
        )


@dataclass(frozen=True, slots=True)
class LangChainModelFactory:
    model: str
    model_kwargs: dict[str, Any] | None = None
    max_retries: int = 0
    structured_output_method: str = "json_schema"
    structured_output_retry_backoff_seconds: float = 1.0
    limiter_registry: LimiterRegistry | None = None
    diagnostic_label: str | None = None
    invocation_timeout_seconds: float | None = None

    def create_structured_invoker(self, *, purpose: str) -> StructuredOutputInvoker:
        if not self.model:
            raise MissingLlmConfigurationError("LangChainModelFactory requires a non-empty model name.")
        try:
            from langchain.chat_models import init_chat_model
        except ImportError as exc:  # pragma: no cover - exercised only in environments missing LangChain
            raise MissingLangChainDependencyError(
                "Install langchain to create a chat model factory."
            ) from exc

        try:
            provider_kwargs = dict(self.model_kwargs or {})
            provider_kwargs["max_retries"] = 0
            chat_model = init_chat_model(self.model, **provider_kwargs)
        except ImportError as exc:  # pragma: no cover - provider package missing
            raise MissingLangChainProviderDependencyError(
                f"Missing provider dependency while initializing model {self.model!r}."
            ) from exc
        invoker = LangChainStructuredInvoker(
            model=chat_model,
            purpose=purpose,
            model_name=self.model,
            diagnostic_label=self.diagnostic_label,
            structured_output_method=self.structured_output_method,
            max_attempts=max_attempts_from_retries(self.max_retries),
            retry_backoff_seconds=self.structured_output_retry_backoff_seconds,
            invocation_timeout_seconds=self.invocation_timeout_seconds,
            limiter_registry=self.limiter_registry,
        )
        return invoker

    def create_tool_calling_invoker(self, *, purpose: str) -> ToolCallingInvoker:
        if not self.model:
            raise MissingLlmConfigurationError("LangChainModelFactory requires a non-empty model name.")
        try:
            from langchain.chat_models import init_chat_model
        except ImportError as exc:  # pragma: no cover - exercised only in environments missing LangChain
            raise MissingLangChainDependencyError(
                "Install langchain to create a chat model factory."
            ) from exc
        try:
            provider_kwargs = dict(self.model_kwargs or {})
            provider_kwargs["max_retries"] = 0
            chat_model = init_chat_model(self.model, **provider_kwargs)
        except ImportError as exc:  # pragma: no cover - provider package missing
            raise MissingLangChainProviderDependencyError(
                f"Missing provider dependency while initializing model {self.model!r}."
            ) from exc
        invoker = LangChainToolCallingInvoker(
            model=chat_model,
            purpose=purpose,
            model_name=self.model,
            diagnostic_label=self.diagnostic_label,
            invocation_timeout_seconds=self.invocation_timeout_seconds,
            max_attempts=max_attempts_from_retries(self.max_retries),
            retry_backoff_seconds=self.structured_output_retry_backoff_seconds,
            limiter_registry=self.limiter_registry,
        )
        return invoker


@dataclass(frozen=True, slots=True)
class OpenAICompatibleChatModelFactory:
    model: str
    api_key: str
    base_url: str
    extra_body: dict[str, Any] | None = None
    default_headers: dict[str, str] | None = None
    use_responses_api: bool = True
    max_tokens: int | None = None
    temperature: float = 0.0
    timeout: float | None = None
    max_retries: int = 1
    model_kwargs: dict[str, Any] | None = None
    structured_output_method: str = "function_calling"
    structured_output_retry_backoff_seconds: float = 1.0
    purpose_policies: dict[str, dict[str, Any]] = field(default_factory=dict)
    limiter_registry: LimiterRegistry | None = None
    diagnostic_label: str | None = None
    context_window_tokens: int | None = None
    default_output_tokens: int | None = None
    tokenizer_enabled: bool = False

    def create_structured_invoker(self, *, purpose: str) -> StructuredOutputInvoker:
        try:
            from langchain.chat_models import init_chat_model
        except ImportError as exc:  # pragma: no cover - exercised only in environments missing provider package
            raise MissingLangChainProviderDependencyError(
                "Install langchain and langchain-openai to use OpenAI-compatible chat models."
            ) from exc

        policy = self._resolve_policy(purpose)
        provider_kwargs = dict(self.model_kwargs or {})
        provider_kwargs["max_retries"] = 0
        chat_model = init_chat_model(
            model=self.model,
            model_provider="openai",
            api_key=self.api_key,
            base_url=self.base_url,
            extra_body=self.extra_body,
            default_headers=self.default_headers,
            use_responses_api=self.use_responses_api,
            max_tokens=policy["max_tokens"],
            temperature=self.temperature,
            timeout=policy["timeout"],
            **provider_kwargs,
        )
        invoker = LangChainStructuredInvoker(
            model=chat_model,
            purpose=purpose,
            model_name=self.model,
            base_url=self.base_url,
            diagnostic_label=self.diagnostic_label,
            structured_output_method=policy["structured_output_method"],
            max_attempts=max_attempts_from_retries(policy["max_retries"]),
            retry_backoff_seconds=policy["structured_output_retry_backoff_seconds"],
            invocation_timeout_seconds=policy["timeout"],
            limiter_registry=self.limiter_registry,
        )
        return invoker

    def create_tool_calling_invoker(self, *, purpose: str) -> ToolCallingInvoker:
        try:
            from langchain.chat_models import init_chat_model
        except ImportError as exc:  # pragma: no cover - exercised only in environments missing provider package
            raise MissingLangChainProviderDependencyError(
                "Install langchain and langchain-openai to use OpenAI-compatible chat models."
            ) from exc

        policy = self._resolve_policy(purpose)
        provider_kwargs = dict(self.model_kwargs or {})
        provider_kwargs["max_retries"] = 0
        chat_model = init_chat_model(
            model=self.model,
            model_provider="openai",
            api_key=self.api_key,
            base_url=self.base_url,
            extra_body=self.extra_body,
            default_headers=self.default_headers,
            use_responses_api=self.use_responses_api,
            max_tokens=policy["max_tokens"],
            temperature=self.temperature,
            timeout=policy["timeout"],
            **provider_kwargs,
        )
        invoker = LangChainToolCallingInvoker(
            model=chat_model,
            purpose=purpose,
            model_name=self.model,
            base_url=self.base_url,
            diagnostic_label=self.diagnostic_label,
            invocation_timeout_seconds=policy["timeout"],
            max_attempts=max_attempts_from_retries(policy["max_retries"]),
            retry_backoff_seconds=policy["structured_output_retry_backoff_seconds"],
            limiter_registry=self.limiter_registry,
            dotted_tool_name_aliasing=_is_micu_base_url(self.base_url),
        )
        return invoker

    def _resolve_policy(self, purpose: str) -> dict[str, Any]:
        override = self.purpose_policies.get(purpose, {})

        def inherit_when_none(key: str, default: Any) -> Any:
            value = override.get(key)
            return default if value is None else value

        return {
            "max_tokens": inherit_when_none("max_tokens", self.max_tokens),
            "timeout": inherit_when_none("timeout", self.timeout),
            "max_retries": inherit_when_none("max_retries", self.max_retries),
            "structured_output_method": inherit_when_none(
                "structured_output_method",
                self.structured_output_method,
            ),
            "structured_output_retry_backoff_seconds": inherit_when_none(
                "structured_output_retry_backoff_seconds",
                self.structured_output_retry_backoff_seconds,
            ),
        }

    def count_prompt_tokens(
        self,
        *,
        system_prompt: str,
        messages: list[Any],
        tools: list[Any],
    ) -> dict[str, Any]:
        if not self.tokenizer_enabled:
            return {"available": False, "error": "tokenizer_disabled"}
        if "open.bigmodel.cn" not in self.base_url and not self.model.startswith("glm-"):
            return {"available": False, "error": "tokenizer_not_supported_for_provider"}
        provider_tools = ProviderToolAdapter(
            dotted_tool_name_aliasing=_is_micu_base_url(self.base_url)
        ).prepare(tools).provider_tools
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                *serialize_llm_payload(messages),
            ],
            "tools": provider_tools,
        }
        try:
            response = self._post_tokenizer_payload(payload)
        except Exception as exc:
            return {
                "available": False,
                "error": str(exc) or exc.__class__.__name__,
            }
        token_count = _extract_tokenizer_count(response)
        if token_count is None:
            return {
                "available": False,
                "error": "tokenizer_response_missing_token_count",
                "response": response,
            }
        return {"available": True, "prompt_tokens": token_count}

    def _post_tokenizer_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = self.base_url.rstrip("/") + "/tokenizer"
        body = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                **(self.default_headers or {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # nosec B310 - endpoint is explicit provider config.
                request,
                timeout=self.timeout or 30.0,
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc)) from exc
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _extract_tokenizer_count(response: dict[str, Any]) -> int | None:
    candidates: list[Any] = [
        response.get("total_tokens"),
        response.get("prompt_tokens"),
        response.get("tokens"),
        response.get("token_count"),
    ]
    usage = response.get("usage")
    if isinstance(usage, dict):
        candidates.extend(
            [
                usage.get("prompt_tokens"),
                usage.get("total_tokens"),
                usage.get("input_tokens"),
            ]
        )
    data = response.get("data")
    if isinstance(data, dict):
        candidates.extend(
            [
                data.get("total_tokens"),
                data.get("prompt_tokens"),
                data.get("tokens"),
                data.get("token_count"),
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, int) and candidate >= 0:
            return candidate
    return None


def _is_micu_base_url(base_url: str | None) -> bool:
    return "micuapi.ai" in (base_url or "").lower()


def _is_retryable_openai_error(exc: Exception) -> bool:
    return is_retryable_llm_provider_error(exc)


__all__ = [
    "ChatModelFactory",
    "LangChainModelFactory",
    "OpenAICompatibleChatModelFactory",
    "LangChainStructuredInvoker",
    "LangChainToolCallingInvoker",
    "LimitedStructuredOutputInvoker",
    "LimitedToolCallingInvoker",
    "MissingLangChainDependencyError",
    "MissingLangChainProviderDependencyError",
    "MissingLlmConfigurationError",
    "StructuredOutputInvoker",
    "ToolCallingInvoker",
]
