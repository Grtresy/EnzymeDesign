from __future__ import annotations

import json
from dataclasses import dataclass
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


class ChatModelFactory(Protocol):
    def create_structured_invoker(self, *, purpose: str) -> StructuredOutputInvoker: ...


@dataclass(frozen=True, slots=True)
class LangChainStructuredInvoker:
    model: Any

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

        structured_model = self.model.with_structured_output(schema)
        response = structured_model.invoke(
            [
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
        )
        if isinstance(response, schema):
            return response
        if isinstance(response, BaseModel):
            return schema.model_validate(response.model_dump())
        return schema.model_validate(response)


@dataclass(frozen=True, slots=True)
class LangChainModelFactory:
    model: str
    model_kwargs: dict[str, Any] | None = None

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
        return LangChainStructuredInvoker(model=chat_model)


@dataclass(frozen=True, slots=True)
class OpenAICompatibleChatModelFactory:
    model: str
    api_key: str
    base_url: str
    temperature: float = 0.0
    timeout: float | None = None
    max_retries: int = 1
    model_kwargs: dict[str, Any] | None = None

    def create_structured_invoker(self, *, purpose: str) -> StructuredOutputInvoker:
        del purpose
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover - exercised only in environments missing provider package
            raise MissingLangChainProviderDependencyError(
                "Install langchain-openai to use OpenAI-compatible chat models."
            ) from exc

        chat_model = ChatOpenAI(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=self.temperature,
            timeout=self.timeout,
            max_retries=self.max_retries,
            model_kwargs=self.model_kwargs or {},
        )
        return LangChainStructuredInvoker(model=chat_model)


__all__ = [
    "ChatModelFactory",
    "LangChainModelFactory",
    "OpenAICompatibleChatModelFactory",
    "LangChainStructuredInvoker",
    "MissingLangChainDependencyError",
    "MissingLangChainProviderDependencyError",
    "MissingLlmConfigurationError",
    "StructuredOutputInvoker",
]
