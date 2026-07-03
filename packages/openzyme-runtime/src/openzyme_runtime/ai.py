from __future__ import annotations

import copy
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
from .llm_debug import serialize_llm_payload


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
        provider_tools, tool_name_aliases = _prepare_provider_tools(
            tools,
            dotted_tool_name_aliasing=self.dotted_tool_name_aliasing,
        )
        provider_to_internal_names = {
            provider_name: internal_name
            for internal_name, provider_name in tool_name_aliases.items()
        }
        provider_messages = _alias_tool_names_in_messages(
            messages,
            tool_name_aliases,
        )
        runnable = self.model.bind_tools(provider_tools)
        request_messages = [SystemMessage(content=system_prompt), *provider_messages]
        request: dict[str, Any] = {
            "system_prompt": system_prompt,
            "messages": serialize_llm_payload(provider_messages),
            "tools": provider_tools,
            "request_messages": serialize_llm_payload(request_messages),
        }
        if tool_name_aliases:
            request["internal_messages"] = serialize_llm_payload(messages)
            request["internal_tools"] = tools
            request["tool_name_aliases"] = tool_name_aliases
        self._log_stage(f"LLM tool-calling start purpose={self.purpose!r}")
        started = time.monotonic()
        response = self._runtime("tool_calling").invoke(
            request=request,
            call=lambda: _restore_tool_names_in_response(
                runnable.invoke(request_messages),
                provider_to_internal_names,
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
    structured_output_method: str = "json_schema"
    structured_output_max_attempts: int = 1
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
            chat_model = init_chat_model(self.model, **(self.model_kwargs or {}))
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
            max_attempts=self.structured_output_max_attempts,
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
            chat_model = init_chat_model(self.model, **(self.model_kwargs or {}))
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
            max_attempts=self.structured_output_max_attempts,
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
    structured_output_max_attempts: int = 3
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
            max_retries=0,
            **(self.model_kwargs or {}),
        )
        invoker = LangChainStructuredInvoker(
            model=chat_model,
            purpose=purpose,
            model_name=self.model,
            base_url=self.base_url,
            diagnostic_label=self.diagnostic_label,
            structured_output_method=policy["structured_output_method"],
            max_attempts=policy["structured_output_max_attempts"],
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
            max_retries=0,
            **(self.model_kwargs or {}),
        )
        invoker = LangChainToolCallingInvoker(
            model=chat_model,
            purpose=purpose,
            model_name=self.model,
            base_url=self.base_url,
            diagnostic_label=self.diagnostic_label,
            invocation_timeout_seconds=policy["timeout"],
            max_attempts=policy["structured_output_max_attempts"],
            retry_backoff_seconds=policy["structured_output_retry_backoff_seconds"],
            limiter_registry=self.limiter_registry,
            dotted_tool_name_aliasing=_is_micu_base_url(self.base_url),
        )
        return invoker

    def _resolve_policy(self, purpose: str) -> dict[str, Any]:
        override = self.purpose_policies.get(purpose, {})
        return {
            "max_tokens": override.get("max_tokens", self.max_tokens),
            "timeout": override.get("timeout", self.timeout),
            "max_retries": override.get("max_retries", self.max_retries),
            "structured_output_method": override.get(
                "structured_output_method",
                self.structured_output_method,
            ),
            "structured_output_max_attempts": override.get(
                "structured_output_max_attempts",
                self.structured_output_max_attempts,
            ),
            "structured_output_retry_backoff_seconds": override.get(
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
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                *serialize_llm_payload(messages),
            ],
            "tools": tools,
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


def _prepare_provider_tools(
    tools: list[Any],
    *,
    dotted_tool_name_aliasing: bool,
) -> tuple[list[Any], dict[str, str]]:
    if not dotted_tool_name_aliasing:
        return tools, {}
    provider_tools = copy.deepcopy(tools)
    aliases: dict[str, str] = {}
    used_names = _provider_tool_names(provider_tools)
    for index, tool in enumerate(provider_tools, start=1):
        function = _tool_function_dict(tool)
        if function is None:
            continue
        original_name = function.get("name")
        if not isinstance(original_name, str) or "." not in original_name:
            continue
        provider_name = _provider_tool_alias(
            original_name,
            used_names=used_names,
            suffix=index,
        )
        function["name"] = provider_name
        aliases[original_name] = provider_name
        used_names.add(provider_name)
    return provider_tools, aliases


def _provider_tool_alias(
    tool_name: str,
    *,
    used_names: set[str],
    suffix: int,
) -> str:
    alias = tool_name.replace(".", "_")
    if alias not in used_names or alias == tool_name:
        return alias
    candidate = f"{alias}_{suffix}"
    counter = suffix
    while candidate in used_names:
        counter += 1
        candidate = f"{alias}_{counter}"
    return candidate


def _provider_tool_names(tools: list[Any]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        function = _tool_function_dict(tool)
        if function is None:
            continue
        name = function.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def _tool_function_dict(tool: Any) -> dict[str, Any] | None:
    if not isinstance(tool, dict):
        return None
    function = tool.get("function")
    return function if isinstance(function, dict) else None


def _alias_tool_names_in_messages(
    messages: list[Any],
    name_map: dict[str, str],
) -> list[Any]:
    if not name_map:
        return messages
    provider_messages = copy.deepcopy(messages)
    for message in provider_messages:
        _replace_tool_names_in_message(message, name_map)
    return provider_messages


def _restore_tool_names_in_response(
    response: Any,
    name_map: dict[str, str],
) -> Any:
    if not name_map:
        return response
    _replace_tool_names_in_message(response, name_map)
    return response


def _replace_tool_names_in_message(message: Any, name_map: dict[str, str]) -> None:
    if isinstance(message, dict):
        _replace_tool_names_in_mapping(message, name_map)
        return
    for attr in ("tool_calls", "invalid_tool_calls", "content", "additional_kwargs"):
        if not hasattr(message, attr):
            continue
        try:
            value = getattr(message, attr)
        except Exception:
            continue
        _replace_tool_names_in_value(value, name_map)
    if hasattr(message, "name"):
        try:
            name = getattr(message, "name")
            if isinstance(name, str) and name in name_map:
                setattr(message, "name", name_map[name])
        except Exception:
            pass


def _replace_tool_names_in_value(value: Any, name_map: dict[str, str]) -> None:
    if isinstance(value, dict):
        _replace_tool_names_in_mapping(value, name_map)
        return
    if isinstance(value, list):
        for item in value:
            _replace_tool_names_in_value(item, name_map)


def _replace_tool_names_in_mapping(
    value: dict[str, Any],
    name_map: dict[str, str],
) -> None:
    name = value.get("name")
    if isinstance(name, str) and name in name_map:
        value["name"] = name_map[name]
    function = value.get("function")
    if isinstance(function, dict):
        function_name = function.get("name")
        if isinstance(function_name, str) and function_name in name_map:
            function["name"] = name_map[function_name]
    for key in ("tool_calls", "invalid_tool_calls", "content"):
        _replace_tool_names_in_value(value.get(key), name_map)
    additional_kwargs = value.get("additional_kwargs")
    if isinstance(additional_kwargs, dict):
        _replace_tool_names_in_mapping(additional_kwargs, name_map)


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
