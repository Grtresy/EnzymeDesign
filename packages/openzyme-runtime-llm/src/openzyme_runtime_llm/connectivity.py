from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .configuration import LlmAdapterConfiguration
from .live_token_ledger import LiveMicuTokenLedger
from .llm_invocation import LlmInvocationRuntime
from .llm_invocation import max_attempts_from_retries


class LlmConnectivityConfigurationError(RuntimeError):
    """Raised before any network effect when a live probe is not exact."""


@dataclass(frozen=True, slots=True)
class LlmConnectivityRequest:
    configuration: LlmAdapterConfiguration
    credential: str
    default_headers: Mapping[str, str]
    use_responses_api: bool
    retry_backoff_seconds: float
    max_output_units: int = 32
    live_token_ledger: LiveMicuTokenLedger | None = None
    live_token_scenario: str | None = None

    def __post_init__(self) -> None:
        if self.configuration.provider_id != "openai":
            raise LlmConnectivityConfigurationError(
                "Responses connectivity probe requires the explicitly selected openai provider"
            )
        if self.configuration.base_url is None:
            raise LlmConnectivityConfigurationError(
                "Responses connectivity probe requires one explicit base URL"
            )
        if not self.credential:
            raise LlmConnectivityConfigurationError(
                "Responses connectivity probe requires selected credential material"
            )
        if not self.use_responses_api:
            raise LlmConnectivityConfigurationError(
                "Responses connectivity probe requires use_responses_api=true"
            )
        if not 0 <= self.retry_backoff_seconds <= 300:
            raise ValueError("retry_backoff_seconds must be within [0, 300]")
        if not 1 <= self.max_output_units <= self.configuration.default_output_units:
            raise ValueError(
                "max_output_units must be positive and within the configured output bound"
            )


def run_connectivity_check(
    request: LlmConnectivityRequest,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Perform one explicit live Responses probe against the selected provider.

    This function never reads environment configuration and never chooses or
    falls back to another Provider. The caller must separately authorize live
    network access; non-live Adapter preflight does not call this function.
    """

    if client_factory is None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise LlmConnectivityConfigurationError(
                "Install the openai extra before running the live connectivity probe"
            ) from exc
        client_factory = OpenAI
    configuration = request.configuration
    client = client_factory(
        api_key=request.credential,
        base_url=configuration.base_url,
        default_headers=dict(request.default_headers),
        timeout=configuration.timeout_seconds,
        max_retries=0,
    )
    input_text = "OpenZyme LLM connectivity check. Reply with exactly: ok"
    response = LlmInvocationRuntime(
        purpose="llm_connectivity",
        kind="connectivity",
        model=configuration.model,
        base_url=configuration.base_url,
        max_attempts=max_attempts_from_retries(configuration.max_retries),
        retry_backoff_seconds=request.retry_backoff_seconds,
        invocation_timeout_seconds=configuration.timeout_seconds,
        diagnostic_label="llm-connectivity",
        live_token_ledger=request.live_token_ledger,
        live_token_scenario=request.live_token_scenario,
        reserved_output_tokens=request.max_output_units,
    ).invoke(
        request={
            "provider_id": configuration.provider_id,
            "provider_backend": "openai.responses",
            "configuration_digest": configuration.configuration_digest,
            "model": configuration.model,
            "use_responses_api": request.use_responses_api,
            "input": input_text,
            "max_output_tokens": request.max_output_units,
        },
        call=lambda: client.responses.create(
            model=configuration.model,
            input=input_text,
            max_output_tokens=request.max_output_units,
        ),
        phase="invoking selected LLM connectivity probe",
    )
    return {
        "status": "ok",
        "provider_id": configuration.provider_id,
        "model": configuration.model,
        "base_url": configuration.base_url,
        "configuration_digest": configuration.configuration_digest,
        "use_responses_api": request.use_responses_api,
        "user_agent": dict(request.default_headers).get("User-Agent"),
        "output_text": extract_response_text(response),
    }


def extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text.strip()
    try:
        payload = response.model_dump()
    except AttributeError:
        payload = response if isinstance(response, dict) else {}
    if not isinstance(payload, dict):
        return ""
    output = payload.get("output")
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return " ".join(parts).strip()


__all__ = [
    "LlmConnectivityConfigurationError",
    "LlmConnectivityRequest",
    "extract_response_text",
    "run_connectivity_check",
]
