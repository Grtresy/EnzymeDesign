from __future__ import annotations

import json
import time
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Protocol
from typing import TypeVar

from pydantic import BaseModel


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
class LangChainStructuredInvoker:
    model: Any
    structured_output_method: str = "json_schema"
    max_attempts: int = 1
    retry_backoff_seconds: float = 1.0

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
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = structured_model.invoke(messages)
                last_error = None
                break
            except Exception as exc:
                if not _is_retryable_openai_error(exc) or attempt >= self.max_attempts:
                    raise
                last_error = exc
                time.sleep(self.retry_backoff_seconds * attempt)
        if response is None and last_error is not None:
            raise last_error
        if isinstance(response, schema):
            return response
        if isinstance(response, BaseModel):
            return schema.model_validate(response.model_dump())
        return schema.model_validate(response)


@dataclass(frozen=True, slots=True)
class LangChainToolCallingInvoker:
    model: Any

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
        return runnable.invoke([SystemMessage(content=system_prompt), *messages])


@dataclass(frozen=True, slots=True)
class LangChainModelFactory:
    model: str
    model_kwargs: dict[str, Any] | None = None
    structured_output_method: str = "json_schema"
    structured_output_max_attempts: int = 1
    structured_output_retry_backoff_seconds: float = 1.0

    def create_structured_invoker(self, *, purpose: str) -> StructuredOutputInvoker:
        del purpose
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
        return LangChainStructuredInvoker(
            model=chat_model,
            structured_output_method=self.structured_output_method,
            max_attempts=self.structured_output_max_attempts,
            retry_backoff_seconds=self.structured_output_retry_backoff_seconds,
        )

    def create_tool_calling_invoker(self, *, purpose: str) -> ToolCallingInvoker:
        del purpose
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
        return LangChainToolCallingInvoker(model=chat_model)


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
        return LangChainStructuredInvoker(
            model=chat_model,
            structured_output_method=policy["structured_output_method"],
            max_attempts=policy["structured_output_max_attempts"],
            retry_backoff_seconds=policy["structured_output_retry_backoff_seconds"],
        )

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
        return LangChainToolCallingInvoker(model=chat_model)

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
    "MissingLangChainDependencyError",
    "MissingLangChainProviderDependencyError",
    "MissingLlmConfigurationError",
    "StructuredOutputInvoker",
    "ToolCallingInvoker",
]
