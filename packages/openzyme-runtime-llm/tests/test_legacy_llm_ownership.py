from __future__ import annotations

from openzyme_runtime_llm import LangChainToolCallingInvoker
from openzyme_runtime_llm import LlmInvocationRuntime
from openzyme_runtime_llm import OpenAICompatibleChatModelFactory
from openzyme_runtime_llm import ProviderToolAdapter


def test_llm_mechanisms_are_owned_by_runtime_llm() -> None:
    assert OpenAICompatibleChatModelFactory.__module__ == "openzyme_runtime_llm.ai"
    assert LangChainToolCallingInvoker.__module__ == "openzyme_runtime_llm.ai"
    assert LlmInvocationRuntime.__module__ == "openzyme_runtime_llm.llm_invocation"
    assert ProviderToolAdapter.__module__ == "openzyme_runtime_llm.provider_tools"
