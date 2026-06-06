from __future__ import annotations

import json
import threading
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
from .llm_debug import current_llm_debug_context
from .llm_debug import get_llm_debug_recorder
from .llm_debug import serialize_llm_payload
from .live_testing import LiveStageTimeout


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
        response: Any | None = None
        last_error: Exception | None = None
        self._log_stage(f"LLM structured start purpose={self.purpose!r}")
        started = time.monotonic()
        for attempt in range(1, self.max_attempts + 1):
            span = get_llm_debug_recorder().begin(
                purpose=self.purpose,
                kind="structured_output",
                model=self.model_name,
                base_url=self.base_url,
                request_context=current_llm_debug_context(),
                request={
                    "system_prompt": system_prompt,
                    "user_payload": user_payload,
                    "schema": schema.model_json_schema(),
                    "structured_output_method": self.structured_output_method,
                    "attempt": attempt,
                    "max_attempts": self.max_attempts,
                    "messages": serialize_llm_payload(messages),
                },
            )
            try:
                phase = (
                    f"invoking LLM structured purpose={self.purpose!r} "
                    f"attempt={attempt}"
                )
                response = self._invoke_provider(
                    phase,
                    lambda: structured_model.invoke(messages),
                )
                parsed_response = (
                    response
                    if isinstance(response, schema)
                    else schema.model_validate(response.model_dump() if isinstance(response, BaseModel) else response)
                )
                span.finish(
                    response={
                        "raw": serialize_llm_payload(response),
                        "parsed": parsed_response.model_dump(),
                    }
                )
                response = parsed_response
                last_error = None
                break
            except Exception as exc:
                span.finish(error=exc)
                if not _is_retryable_openai_error(exc) or attempt >= self.max_attempts:
                    raise
                last_error = exc
                time.sleep(self.retry_backoff_seconds * attempt)
        if response is None and last_error is not None:
            raise last_error
        if isinstance(response, schema):
            self._log_stage(
                f"LLM structured finished elapsed={time.monotonic() - started:.2f}s"
            )
            return response
        parsed = schema.model_validate(response)
        self._log_stage(
            f"LLM structured finished elapsed={time.monotonic() - started:.2f}s"
        )
        return parsed

    def _log_stage(self, message: str) -> None:
        if self.diagnostic_label is None:
            return
        print(f"[{self.diagnostic_label}] {message}", flush=True)

    def _invoke_provider(self, phase: str, invoke: Any) -> Any:
        if self.diagnostic_label is None or self.invocation_timeout_seconds is None:
            return invoke()
        if threading.current_thread() is not threading.main_thread():
            self._log_stage(
                f"LLM provider timeout not armed outside main thread phase={phase!r}"
            )
            return invoke()
        with LiveStageTimeout(
            phase,
            self.invocation_timeout_seconds,
            hard_exit=False,
        ):
            return invoke()


@dataclass(frozen=True, slots=True)
class LangChainToolCallingInvoker:
    model: Any
    purpose: str = "tool_calling"
    model_name: str | None = None
    base_url: str | None = None
    diagnostic_label: str | None = None
    invocation_timeout_seconds: float | None = None

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
        runnable = self.model.bind_tools(tools)
        request_messages = [SystemMessage(content=system_prompt), *messages]
        span = get_llm_debug_recorder().begin(
            purpose=self.purpose,
            kind="tool_calling",
            model=self.model_name,
            base_url=self.base_url,
            request_context=current_llm_debug_context(),
            request={
                "system_prompt": system_prompt,
                "messages": serialize_llm_payload(messages),
                "tools": tools,
                "request_messages": serialize_llm_payload(request_messages),
            },
        )
        self._log_stage(f"LLM tool-calling start purpose={self.purpose!r}")
        started = time.monotonic()
        try:
            response = self._invoke_provider(
                f"invoking LLM tool-calling purpose={self.purpose!r} attempt=1",
                lambda: runnable.invoke(request_messages),
            )
        except Exception as exc:
            span.finish(error=exc)
            raise
        span.finish(response=response)
        self._log_stage(
            f"LLM tool-calling finished elapsed={time.monotonic() - started:.2f}s"
        )
        return response

    def _log_stage(self, message: str) -> None:
        if self.diagnostic_label is None:
            return
        print(f"[{self.diagnostic_label}] {message}", flush=True)

    def _invoke_provider(self, phase: str, invoke: Any) -> Any:
        if self.diagnostic_label is None or self.invocation_timeout_seconds is None:
            return invoke()
        if threading.current_thread() is not threading.main_thread():
            self._log_stage(
                f"LLM provider timeout not armed outside main thread phase={phase!r}"
            )
            return invoke()
        with LiveStageTimeout(
            phase,
            self.invocation_timeout_seconds,
            hard_exit=False,
        ):
            return invoke()


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
        )
        if self.limiter_registry is None:
            return invoker
        return LimitedStructuredOutputInvoker(invoker, self.limiter_registry)

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
        )
        if self.limiter_registry is None:
            return invoker
        return LimitedToolCallingInvoker(invoker, self.limiter_registry)


@dataclass(frozen=True, slots=True)
class OpenAICompatibleChatModelFactory:
    model: str
    api_key: str
    base_url: str
    extra_body: dict[str, Any] | None = None
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
            max_tokens=policy["max_tokens"],
            temperature=self.temperature,
            timeout=policy["timeout"],
            max_retries=policy["max_retries"],
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
        )
        if self.limiter_registry is None:
            return invoker
        return LimitedStructuredOutputInvoker(invoker, self.limiter_registry)

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
            max_tokens=policy["max_tokens"],
            temperature=self.temperature,
            timeout=policy["timeout"],
            max_retries=policy["max_retries"],
            **(self.model_kwargs or {}),
        )
        invoker = LangChainToolCallingInvoker(
            model=chat_model,
            purpose=purpose,
            model_name=self.model,
            base_url=self.base_url,
            diagnostic_label=self.diagnostic_label,
            invocation_timeout_seconds=policy["timeout"],
        )
        if self.limiter_registry is None:
            return invoker
        return LimitedToolCallingInvoker(invoker, self.limiter_registry)

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


def _is_retryable_openai_error(exc: Exception) -> bool:
    try:
        from openai import APIStatusError
        from openai import APIConnectionError
        from openai import APITimeoutError
        from openai import RateLimitError
    except ImportError:
        return False
    if isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in {429, 500, 502, 503, 504}
    return False


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
