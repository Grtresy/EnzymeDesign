from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
import json
from typing import Any
from typing import Protocol

from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier

from .configuration import LlmAdapterConfiguration


LLM_PROVIDER_BACKEND_CONTRACT = "openzyme.llm-provider-backend@1"
LLM_PROVIDER_BACKEND_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": LLM_PROVIDER_BACKEND_CONTRACT,
        "methods": ["invoke"],
        "exact_provider": True,
        "silent_provider_switch": False,
        "credential_in_projection": False,
    }
)


class LlmProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        phase: str = "provider_invoke",
    ) -> None:
        super().__init__(message)
        require_identifier(code, field_name="code")
        require_identifier(phase, field_name="phase")
        self.code = code
        self.retryable = retryable
        self.phase = phase
        self.mutation_applied = False
        self.fallback_performed = False


@dataclass(frozen=True, slots=True)
class ProviderToolCall:
    call_id: str
    tool_name: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        require_identifier(self.call_id, field_name="call_id")
        require_identifier(self.tool_name, field_name="tool_name")
        canonical_sha256_digest({"arguments": dict(self.arguments)})


@dataclass(frozen=True, slots=True)
class ProviderTurnRequest:
    provider_id: str
    model: str
    messages: tuple[dict[str, Any], ...]
    tools: tuple[ToolSpec, ...]
    max_output_units: int
    timeout_seconds: float
    attempt: int
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderTurnResponse:
    content: str
    tool_calls: tuple[ProviderToolCall, ...] = ()
    input_units: int = 0
    output_units: int = 0
    provider_reported_usage: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or len(self.content) > 262_144:
            raise ValueError("provider response content must be bounded text")
        for field_name in ("input_units", "output_units"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")


class LlmProviderBackend(Protocol):
    provider_id: str
    backend_identity_digest: str

    def invoke(self, request: ProviderTurnRequest) -> ProviderTurnResponse: ...


@dataclass(slots=True)
class LangChainProviderBackend:
    """Lazy LangChain implementation for one exact configured provider.

    Construction performs no import or network access.  The provider package is
    loaded only after Distribution selection and Adapter preflight.
    """

    configuration: LlmAdapterConfiguration
    api_key: str = field(repr=False)
    provider_id: str = field(init=False)
    backend_identity_digest: str = field(init=False)
    _model: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key:
            raise ValueError("the selected credential slot did not resolve a credential")
        self.provider_id = self.configuration.provider_id
        self.backend_identity_digest = canonical_sha256_digest(
            {
                "backend": "langchain",
                "provider_id": self.provider_id,
                "configuration_digest": self.configuration.configuration_digest,
                "credential_present": True,
            }
        )

    def preflight(self) -> dict[str, Any]:
        try:
            from langchain.chat_models import init_chat_model  # noqa: F401
        except ImportError as exc:
            raise LlmProviderError(
                "llm_provider_dependency_missing",
                "selected LangChain provider dependency is unavailable",
                retryable=False,
                phase="adapter_preflight",
            ) from exc
        return {
            "provider_id": self.provider_id,
            "backend_identity_digest": self.backend_identity_digest,
            "configuration_digest": self.configuration.configuration_digest,
            "credential_present": True,
            "network_probe_performed": False,
        }

    def invoke(self, request: ProviderTurnRequest) -> ProviderTurnResponse:
        if request.provider_id != self.provider_id:
            raise LlmProviderError(
                "llm_provider_identity_drift",
                "runtime request targets another provider",
                retryable=False,
            )
        model = self._model_instance()
        try:
            bound = model.bind_tools([item.to_openai_tool() for item in request.tools])
            response = bound.invoke(list(request.messages))
        except Exception as exc:
            raise LlmProviderError(
                "llm_provider_call_failed",
                "selected LLM provider call failed",
                retryable=_retryable_provider_exception(exc),
            ) from exc
        tool_calls = tuple(_parse_langchain_tool_call(item) for item in _tool_calls(response))
        content = _response_content(response)
        input_units, output_units, provider_reported = _usage(response)
        return ProviderTurnResponse(
            content=content,
            tool_calls=tool_calls,
            input_units=input_units,
            output_units=output_units,
            provider_reported_usage=provider_reported,
        )

    def _model_instance(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from langchain.chat_models import init_chat_model
        except ImportError as exc:
            raise LlmProviderError(
                "llm_provider_dependency_missing",
                "selected LangChain provider dependency is unavailable",
                retryable=False,
                phase="adapter_preflight",
            ) from exc
        options = dict(self.configuration.provider_options)
        implementation_provider = options.pop(
            "langchain_model_provider",
            self.configuration.provider_id,
        )
        if not isinstance(implementation_provider, str) or not implementation_provider:
            raise LlmProviderError(
                "llm_provider_implementation_identity_invalid",
                "selected LangChain implementation provider identity is invalid",
                retryable=False,
                phase="adapter_preflight",
            )
        options["max_retries"] = 0
        options["timeout"] = self.configuration.timeout_seconds
        if self.configuration.base_url is not None:
            options["base_url"] = self.configuration.base_url
        options["api_key"] = self.api_key
        try:
            self._model = init_chat_model(
                model=self.configuration.model,
                model_provider=implementation_provider,
                **options,
            )
        except Exception as exc:
            raise LlmProviderError(
                "llm_provider_initialization_failed",
                "selected LangChain provider could not be initialized",
                retryable=False,
                phase="adapter_preflight",
            ) from exc
        return self._model


def _tool_calls(response: Any) -> tuple[Any, ...]:
    value = getattr(response, "tool_calls", ())
    return tuple(value or ())


def _parse_langchain_tool_call(value: Any) -> ProviderToolCall:
    if not isinstance(value, Mapping):
        raise LlmProviderError(
            "llm_provider_response_invalid",
            "provider returned a non-object tool call",
            retryable=False,
            phase="provider_response",
        )
    call_id = value.get("id")
    name = value.get("name")
    arguments = value.get("args", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise LlmProviderError(
                "llm_provider_tool_arguments_invalid",
                "provider returned invalid JSON tool arguments",
                retryable=False,
                phase="provider_response",
            ) from exc
    if not isinstance(arguments, Mapping):
        raise LlmProviderError(
            "llm_provider_tool_arguments_invalid",
            "provider tool arguments must be an object",
            retryable=False,
            phase="provider_response",
        )
    return ProviderToolCall(
        call_id=str(call_id),
        tool_name=str(name),
        arguments=arguments,
    )


def _response_content(response: Any) -> str:
    value = getattr(response, "content", "")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _usage(response: Any) -> tuple[int, int, bool]:
    metadata = getattr(response, "usage_metadata", None)
    if not isinstance(metadata, Mapping):
        return 0, 0, False
    input_units = metadata.get("input_tokens", metadata.get("input_units", 0))
    output_units = metadata.get("output_tokens", metadata.get("output_units", 0))
    if (
        not isinstance(input_units, int)
        or isinstance(input_units, bool)
        or input_units < 0
        or not isinstance(output_units, int)
        or isinstance(output_units, bool)
        or output_units < 0
    ):
        return 0, 0, False
    return input_units, output_units, True


def _retryable_provider_exception(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    return status in {408, 409, 429, 500, 502, 503, 504}


__all__ = [
    "LLM_PROVIDER_BACKEND_CONTRACT",
    "LLM_PROVIDER_BACKEND_CONTRACT_DIGEST",
    "LangChainProviderBackend",
    "LlmProviderBackend",
    "LlmProviderError",
    "ProviderToolCall",
    "ProviderTurnRequest",
    "ProviderTurnResponse",
]
