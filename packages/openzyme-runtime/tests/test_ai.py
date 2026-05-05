from __future__ import annotations

import sys
from types import ModuleType

from pydantic import BaseModel

from openzyme_runtime.ai import LangChainStructuredInvoker
from openzyme_runtime.ai import LangChainToolCallingInvoker
from openzyme_runtime.ai import OpenAICompatibleChatModelFactory
from openzyme_runtime.ai import _is_retryable_openai_error
from openzyme_runtime.llm_debug import get_llm_debug_recorder
from openzyme_runtime.llm_debug import llm_debug_context


class ExampleSchema(BaseModel):
    value: str


class RetryableTimeoutError(Exception):
    pass


def test_structured_invoker_retries_retryable_openai_errors(monkeypatch) -> None:
    get_llm_debug_recorder().clear()
    attempts = {"count": 0}

    class FakeStructuredModel:
        def invoke(self, messages):
            del messages
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RetryableTimeoutError("transient timeout")
            return ExampleSchema(value="ok")

    class FakeModel:
        def with_structured_output(self, schema, *, method: str):
            assert schema is ExampleSchema
            assert method == "function_calling"
            return FakeStructuredModel()

    monkeypatch.setattr(
        "openzyme_runtime.ai._is_retryable_openai_error",
        lambda exc: isinstance(exc, RetryableTimeoutError),
    )

    invoker = LangChainStructuredInvoker(
        model=FakeModel(),
        structured_output_method="function_calling",
        max_attempts=3,
        retry_backoff_seconds=0.0,
    )

    result = invoker.invoke_structured(
        schema=ExampleSchema,
        system_prompt="Return the schema.",
        user_payload={"value": "ignored"},
    )

    assert result.value == "ok"
    assert attempts["count"] == 3
    records = get_llm_debug_recorder().list_records(limit=10, purpose="structured_output")
    assert [record["status"] for record in records[:3]] == ["succeeded", "error", "error"]
    assert records[0]["request"]["attempt"] == 3
    assert records[0]["response"]["parsed"] == {"value": "ok"}


def test_structured_invoker_does_not_retry_non_retryable_errors(monkeypatch) -> None:
    get_llm_debug_recorder().clear()
    attempts = {"count": 0}

    class FakeStructuredModel:
        def invoke(self, messages):
            del messages
            attempts["count"] += 1
            raise ValueError("bad schema")

    class FakeModel:
        def with_structured_output(self, schema, *, method: str):
            assert schema is ExampleSchema
            assert method == "function_calling"
            return FakeStructuredModel()

    monkeypatch.setattr("openzyme_runtime.ai._is_retryable_openai_error", lambda exc: False)

    invoker = LangChainStructuredInvoker(
        model=FakeModel(),
        structured_output_method="function_calling",
        max_attempts=3,
        retry_backoff_seconds=0.0,
    )

    try:
        invoker.invoke_structured(
            schema=ExampleSchema,
            system_prompt="Return the schema.",
            user_payload={"value": "ignored"},
        )
    except ValueError as exc:
        assert str(exc) == "bad schema"
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")

    assert attempts["count"] == 1
    records = get_llm_debug_recorder().list_records(limit=1, purpose="structured_output")
    assert records[0]["status"] == "error"
    assert records[0]["error"]["message"] == "bad schema"


def test_tool_calling_invoker_records_request_response_and_context() -> None:
    get_llm_debug_recorder().clear()

    class FakeRunnable:
        def invoke(self, messages):
            return {"content": "ok", "tool_calls": [], "message_count": len(messages)}

    class FakeModel:
        def bind_tools(self, tools):
            assert tools == [{"type": "function", "function": {"name": "task.list"}}]
            return FakeRunnable()

    invoker = LangChainToolCallingInvoker(
        model=FakeModel(),
        purpose="v3_harness_loop",
        model_name="fake-model",
        base_url="https://example.test/v1",
    )
    with llm_debug_context(session_id="sess_001"):
        response = invoker.invoke_with_tools(
            system_prompt="You are master.",
            messages=[],
            tools=[{"type": "function", "function": {"name": "task.list"}}],
        )

    records = get_llm_debug_recorder().list_records(limit=1)
    assert response["content"] == "ok"
    assert records[0]["purpose"] == "v3_harness_loop"
    assert records[0]["kind"] == "tool_calling"
    assert records[0]["model"] == "fake-model"
    assert records[0]["base_url"] == "https://example.test/v1"
    assert records[0]["request_context"]["session_id"] == "sess_001"
    assert records[0]["request"]["system_prompt"] == "You are master."
    assert records[0]["response"]["content"] == "ok"


def test_openai_compatible_factory_uses_init_chat_model_and_purpose_policy(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class FakeStructuredModel:
        def with_structured_output(self, schema, *, method: str):
            observed["schema"] = schema
            observed["method"] = method

            class _Runnable:
                def invoke(self, messages):
                    observed["messages"] = messages
                    return ExampleSchema(value="ok")

            return _Runnable()

    def fake_init_chat_model(model: str, *, model_provider: str, **kwargs):
        observed["model"] = model
        observed["model_provider"] = model_provider
        observed["kwargs"] = kwargs
        return FakeStructuredModel()

    monkeypatch.setattr("openzyme_runtime.ai.init_chat_model", fake_init_chat_model, raising=False)
    monkeypatch.setattr(
        "langchain.chat_models.init_chat_model",
        fake_init_chat_model,
        raising=False,
    )

    factory = OpenAICompatibleChatModelFactory(
        model="glm-5.1",
        api_key="llm-key",
        base_url="https://example.test/v1",
        extra_body={"provider": "bigmodel"},
        max_tokens=700,
        timeout=30.0,
        max_retries=1,
        structured_output_method="function_calling",
        structured_output_max_attempts=3,
        structured_output_retry_backoff_seconds=1.0,
        purpose_policies={
            "report_review": {
                "timeout": 90.0,
                "max_tokens": 300,
                "max_retries": 0,
                "structured_output_method": "json_mode",
                "structured_output_max_attempts": 2,
                "structured_output_retry_backoff_seconds": 0.5,
            }
        },
    )

    invoker = factory.create_structured_invoker(purpose="report_review")
    result = invoker.invoke_structured(
        schema=ExampleSchema,
        system_prompt="Return the schema.",
        user_payload={"value": "ignored"},
    )

    assert result.value == "ok"
    assert observed["model"] == "glm-5.1"
    assert observed["model_provider"] == "openai"
    assert observed["method"] == "json_mode"
    assert observed["kwargs"] == {
        "api_key": "llm-key",
        "base_url": "https://example.test/v1",
        "extra_body": {"provider": "bigmodel"},
        "max_tokens": 300,
        "temperature": 0.0,
        "timeout": 90.0,
        "max_retries": 0,
    }


def test_retryable_openai_error_recognizes_rate_limit_and_transient_status(monkeypatch) -> None:
    class FakeRateLimitError(Exception):
        pass

    class FakeApiStatusError(Exception):
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    fake_openai = ModuleType("openai")
    fake_openai.RateLimitError = FakeRateLimitError
    fake_openai.APIStatusError = FakeApiStatusError
    fake_openai.APITimeoutError = type("FakeTimeoutError", (Exception,), {})
    fake_openai.APIConnectionError = type("FakeConnectionError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    assert _is_retryable_openai_error(FakeRateLimitError())
    assert _is_retryable_openai_error(FakeApiStatusError(429))
    assert _is_retryable_openai_error(FakeApiStatusError(503))
    assert not _is_retryable_openai_error(FakeApiStatusError(400))
