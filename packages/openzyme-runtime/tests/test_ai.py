from __future__ import annotations

import asyncio
import sys
import threading
import time
from types import ModuleType

from pydantic import BaseModel

from openzyme_runtime import LimiterRegistry
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


def test_tool_calling_invoker_aliases_dotted_tool_names_for_provider() -> None:
    from langchain_core.messages import AIMessage
    from langchain_core.messages import ToolMessage

    get_llm_debug_recorder().clear()

    class FakeRunnable:
        def invoke(self, messages):
            previous_ai = messages[1]
            previous_tool = messages[2]
            assert previous_ai.tool_calls[0]["name"] == "task_create"
            assert previous_ai.content[0]["name"] == "task_create"
            assert previous_tool.name == "task_create"
            return AIMessage(
                content=[
                    {
                        "type": "function_call",
                        "name": "task_create",
                        "arguments": '{"subject":"new task"}',
                        "call_id": "call_new",
                    }
                ],
                tool_calls=[
                    {
                        "name": "task_create",
                        "args": {"subject": "new task"},
                        "id": "call_new",
                        "type": "tool_call",
                    }
                ],
            )

    class FakeModel:
        def bind_tools(self, tools):
            assert tools[0]["function"]["name"] == "task_create"
            return FakeRunnable()

    invoker = LangChainToolCallingInvoker(
        model=FakeModel(),
        purpose="v3_harness_loop",
        model_name="fake-model",
        base_url="https://www.micuapi.ai/v1",
        dotted_tool_name_aliasing=True,
    )
    response = invoker.invoke_with_tools(
        system_prompt="You are master.",
        messages=[
            AIMessage(
                content=[
                    {
                        "type": "function_call",
                        "name": "task.create",
                        "arguments": '{"subject":"old task"}',
                        "call_id": "call_old",
                    }
                ],
                tool_calls=[
                    {
                        "name": "task.create",
                        "args": {"subject": "old task"},
                        "id": "call_old",
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(content='{"ok":true}', tool_call_id="call_old", name="task.create"),
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "task.create",
                    "description": "Create a task.",
                    "parameters": {
                        "type": "object",
                        "properties": {"subject": {"type": "string"}},
                        "required": ["subject"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
    )

    records = get_llm_debug_recorder().list_records(limit=1)
    assert response.tool_calls[0]["name"] == "task.create"
    assert response.content[0]["name"] == "task.create"
    assert records[0]["request"]["tools"][0]["function"]["name"] == "task_create"
    assert records[0]["request"]["internal_tools"][0]["function"]["name"] == "task.create"
    assert records[0]["request"]["tool_name_aliases"] == {"task.create": "task_create"}
    assert records[0]["response"]["tool_calls"][0]["name"] == "task.create"


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
        model="gpt-5-mini",
        api_key="llm-key",
        base_url="https://example.test/v1",
        default_headers={"User-Agent": "openzyme-test-agent"},
        use_responses_api=True,
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
    assert isinstance(invoker, LangChainStructuredInvoker)
    assert invoker.invocation_timeout_seconds == 90.0
    result = invoker.invoke_structured(
        schema=ExampleSchema,
        system_prompt="Return the schema.",
        user_payload={"value": "ignored"},
    )

    assert result.value == "ok"
    assert observed["model"] == "gpt-5-mini"
    assert observed["model_provider"] == "openai"
    assert observed["method"] == "json_mode"
    assert observed["kwargs"] == {
        "api_key": "llm-key",
        "base_url": "https://example.test/v1",
        "extra_body": None,
        "default_headers": {"User-Agent": "openzyme-test-agent"},
        "use_responses_api": True,
        "max_tokens": 300,
        "temperature": 0.0,
        "timeout": 90.0,
        "max_retries": 0,
    }


def test_openai_compatible_factory_aliases_dotted_tool_names_only_for_micu(monkeypatch) -> None:
    class FakeModel:
        def bind_tools(self, tools):
            del tools
            raise AssertionError("tool invocation is not part of this factory test")

    monkeypatch.setattr(
        "langchain.chat_models.init_chat_model",
        lambda *args, **kwargs: FakeModel(),
        raising=False,
    )

    micu_factory = OpenAICompatibleChatModelFactory(
        model="gpt-5.5",
        api_key="llm-key",
        base_url="https://www.micuapi.ai/v1",
    )
    micu_invoker = micu_factory.create_tool_calling_invoker(purpose="v3_harness_loop")

    assert isinstance(micu_invoker, LangChainToolCallingInvoker)
    assert micu_invoker.dotted_tool_name_aliasing is True

    other_factory = OpenAICompatibleChatModelFactory(
        model="gpt-5.5",
        api_key="llm-key",
        base_url="https://example.test/v1",
    )
    other_invoker = other_factory.create_tool_calling_invoker(purpose="v3_harness_loop")

    assert isinstance(other_invoker, LangChainToolCallingInvoker)
    assert other_invoker.dotted_tool_name_aliasing is False


def test_openai_compatible_factory_counts_bigmodel_prompt_tokens(monkeypatch) -> None:
    observed: dict[str, object] = {}
    factory = OpenAICompatibleChatModelFactory(
        model="glm-5.1",
        api_key="llm-key",
        base_url="https://open.bigmodel.cn/api/coding/paas/v4",
        tokenizer_enabled=True,
    )

    def fake_post(_self, payload: dict[str, object]) -> dict[str, object]:
        observed["payload"] = payload
        return {"usage": {"prompt_tokens": 123}}

    monkeypatch.setattr(OpenAICompatibleChatModelFactory, "_post_tokenizer_payload", fake_post)

    result = factory.count_prompt_tokens(
        system_prompt="You are master.",
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "task.list"}}],
    )

    payload = observed["payload"]
    assert result == {"available": True, "prompt_tokens": 123}
    assert payload["model"] == "glm-5.1"
    assert payload["messages"][0] == {"role": "system", "content": "You are master."}
    assert payload["tools"] == [{"type": "function", "function": {"name": "task.list"}}]


def test_openai_compatible_factory_tokenizer_failure_is_unavailable(monkeypatch) -> None:
    factory = OpenAICompatibleChatModelFactory(
        model="glm-5.1",
        api_key="llm-key",
        base_url="https://open.bigmodel.cn/api/coding/paas/v4",
        tokenizer_enabled=True,
    )

    def fail_post(_self, _payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("tokenizer offline")

    monkeypatch.setattr(OpenAICompatibleChatModelFactory, "_post_tokenizer_payload", fail_post)

    result = factory.count_prompt_tokens(
        system_prompt="system",
        messages=[],
        tools=[],
    )

    assert result["available"] is False
    assert result["error"] == "tokenizer offline"


def test_diagnostic_structured_invoker_wraps_provider_call_with_stage_timeout(monkeypatch) -> None:
    observed: list[tuple[str, float, bool]] = []

    class FakeTimeout:
        def __init__(self, phase, seconds, *, hard_exit=True, **kwargs):
            del kwargs
            observed.append((phase, seconds, hard_exit))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeStructuredModel:
        def invoke(self, messages):
            del messages
            return ExampleSchema(value="ok")

    class FakeModel:
        def with_structured_output(self, schema, *, method: str):
            assert schema is ExampleSchema
            assert method == "function_calling"
            return FakeStructuredModel()

    monkeypatch.setattr("openzyme_runtime.ai.LiveStageTimeout", FakeTimeout)

    invoker = LangChainStructuredInvoker(
        model=FakeModel(),
        purpose="design_next_action",
        diagnostic_label="live-provider",
        structured_output_method="function_calling",
        invocation_timeout_seconds=12.5,
    )

    result = invoker.invoke_structured(
        schema=ExampleSchema,
        system_prompt="Return the schema.",
        user_payload={"value": "ignored"},
    )

    assert result.value == "ok"
    assert observed == [
        ("invoking LLM structured purpose='design_next_action' attempt=1", 12.5, False)
    ]


def test_diagnostic_tool_invoker_wraps_provider_call_with_stage_timeout(monkeypatch) -> None:
    observed: list[tuple[str, float, bool]] = []

    class FakeTimeout:
        def __init__(self, phase, seconds, *, hard_exit=True, **kwargs):
            del kwargs
            observed.append((phase, seconds, hard_exit))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeRunnable:
        def invoke(self, messages):
            del messages
            return {"content": "ok"}

    class FakeModel:
        def bind_tools(self, tools):
            assert tools == []
            return FakeRunnable()

    monkeypatch.setattr("openzyme_runtime.ai.LiveStageTimeout", FakeTimeout)

    invoker = LangChainToolCallingInvoker(
        model=FakeModel(),
        purpose="deep_research_researcher",
        diagnostic_label="live-provider",
        invocation_timeout_seconds=7.0,
    )
    response = invoker.invoke_with_tools(
        system_prompt="Use tools.",
        messages=[],
        tools=[],
    )

    assert response == {"content": "ok"}
    assert observed == [
        ("invoking LLM tool-calling purpose='deep_research_researcher' attempt=1", 7.0, False)
    ]


def test_openai_compatible_factory_limits_structured_and_tool_invocations(monkeypatch) -> None:
    lock = threading.Lock()
    active = 0
    observed_max = 0

    def enter_provider() -> None:
        nonlocal active, observed_max
        with lock:
            active += 1
            observed_max = max(observed_max, active)

    def leave_provider() -> None:
        nonlocal active
        with lock:
            active -= 1

    class FakeStructuredRunnable:
        def invoke(self, messages):
            del messages
            enter_provider()
            try:
                time.sleep(0.01)
                return ExampleSchema(value="ok")
            finally:
                leave_provider()

    class FakeToolRunnable:
        def invoke(self, messages):
            del messages
            enter_provider()
            try:
                time.sleep(0.01)
                return {"content": "ok"}
            finally:
                leave_provider()

    class FakeModel:
        def with_structured_output(self, schema, *, method: str):
            del schema, method
            return FakeStructuredRunnable()

        def bind_tools(self, tools):
            del tools
            return FakeToolRunnable()

    monkeypatch.setattr(
        "langchain.chat_models.init_chat_model",
        lambda *args, **kwargs: FakeModel(),
        raising=False,
    )
    registry = LimiterRegistry({"llm_provider": 2})
    factory = OpenAICompatibleChatModelFactory(
        model="glm-5.1",
        api_key="llm-key",
        base_url="https://example.test/v1",
        limiter_registry=registry,
    )
    structured = factory.create_structured_invoker(purpose="test_structured")
    tool_calling = factory.create_tool_calling_invoker(purpose="test_tools")

    async def run_structured_calls() -> None:
        await asyncio.gather(
            *(
                asyncio.to_thread(
                    structured.invoke_structured,
                    schema=ExampleSchema,
                    system_prompt="Return schema.",
                    user_payload={"value": "ignored"},
                )
                for _ in range(10)
            )
        )

    async def run_tool_calls() -> None:
        await asyncio.gather(
            *(
                asyncio.to_thread(
                    tool_calling.invoke_with_tools,
                    system_prompt="Use tools.",
                    messages=[],
                    tools=[],
                )
                for _ in range(10)
            )
        )

    asyncio.run(run_structured_calls())
    asyncio.run(run_tool_calls())

    assert observed_max <= 2


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
