from __future__ import annotations

import json
from typing import Any

from .llm_invocation import LlmInvocationRuntime
from .llm_invocation import max_attempts_from_retries
from .live_token_ledger import is_micu_provider_url
from .live_token_ledger import LiveMicuTokenLedger
from .settings import get_settings


class LlmConnectivityConfigurationError(RuntimeError):
    """Raised when the configured LLM settings cannot run a live smoke call."""


def run_connectivity_check() -> dict[str, Any]:
    settings = get_settings()
    llm = settings.llm
    if not llm.api_key:
        raise LlmConnectivityConfigurationError(
            "OPENZYME_LLM_API_KEY or MICU_API_KEY is required."
        )
    if not llm.model:
        raise LlmConnectivityConfigurationError("OPENZYME_LLM_MODEL is required.")
    if not llm.base_url:
        raise LlmConnectivityConfigurationError("OPENZYME_LLM_BASE_URL is required.")
    if not llm.use_responses_api:
        raise LlmConnectivityConfigurationError(
            "OPENZYME_LLM_USE_RESPONSES_API must be true for this Responses API smoke check."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise LlmConnectivityConfigurationError(
            "Install langchain-openai/openai dependencies before running the LLM smoke check."
        ) from exc

    client = OpenAI(
        api_key=llm.api_key,
        base_url=llm.base_url,
        default_headers=llm.default_headers,
        timeout=llm.timeout or 60.0,
        max_retries=0,
    )
    output_token_reservation = _smoke_max_output_tokens(llm.max_tokens)
    live_token_ledger = (
        LiveMicuTokenLedger(settings.test.live_llm.token_ledger_path)
        if is_micu_provider_url(llm.base_url)
        else None
    )
    input_text = "OpenZyme LLM connectivity check. Reply with exactly: ok"
    response = LlmInvocationRuntime(
        purpose="llm_connectivity",
        kind="connectivity",
        model=llm.model,
        base_url=llm.base_url,
        max_attempts=max_attempts_from_retries(llm.max_retries),
        retry_backoff_seconds=llm.structured_output_retry_backoff_seconds,
        invocation_timeout_seconds=llm.timeout or 60.0,
        diagnostic_label="llm-connectivity",
        live_token_ledger=live_token_ledger,
        live_token_scenario="llm_connectivity" if live_token_ledger is not None else None,
        reserved_output_tokens=output_token_reservation,
    ).invoke(
        request={
            "model": llm.model,
            "use_responses_api": llm.use_responses_api,
            "input": input_text,
            "max_output_tokens": output_token_reservation,
        },
        call=lambda: client.responses.create(
            model=llm.model,
            input=input_text,
            max_output_tokens=output_token_reservation,
        ),
        phase="invoking LLM connectivity check",
    )
    return {
        "status": "ok",
        "model": llm.model,
        "base_url": llm.base_url,
        "use_responses_api": llm.use_responses_api,
        "user_agent": (llm.default_headers or {}).get("User-Agent"),
        "output_text": _extract_response_text(response),
    }


def _smoke_max_output_tokens(configured_max_tokens: int | None) -> int:
    if configured_max_tokens is None:
        return 32
    return max(1, min(configured_max_tokens, 32))


def _extract_response_text(response: Any) -> str:
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


def main() -> None:
    result = run_connectivity_check()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
