from __future__ import annotations

from openzyme_core import ModelContextProfile
from openzyme_core import PromptBudgetAction
from openzyme_core import PromptBudgetConfig
from openzyme_core import PromptTokenEstimate
from openzyme_core import PromptTokenEstimator
from openzyme_core import decide_prompt_budget
from openzyme_core import model_context_profile_from_env_or_factory


def test_glm_51_profile_defaults_to_bigmodel_context_window(monkeypatch) -> None:
    monkeypatch.delenv("OPENZYME_LLM_CONTEXT_WINDOW_TOKENS", raising=False)
    monkeypatch.delenv("OPENZYME_LLM_DEFAULT_OUTPUT_TOKENS", raising=False)

    class Factory:
        model = "glm-5.1"

    profile = model_context_profile_from_env_or_factory(Factory())

    assert profile.context_window_tokens == 200_000
    assert profile.default_output_tokens == 65_536
    assert profile.max_output_tokens == 131_072
    assert profile.profile_known is True


def test_prompt_estimator_counts_system_messages_tools_and_observations() -> None:
    estimate = PromptTokenEstimator().estimate(
        system_prompt="system prompt",
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "task.list"}}],
        tool_observations=[{"ok": True, "content": "done"}],
    )

    assert estimate.prompt_tokens > 0
    assert estimate.breakdown["system_prompt"] > 0
    assert estimate.breakdown["messages"] > 0
    assert estimate.breakdown["tools"] > 0
    assert estimate.breakdown["tool_observations"] > 0


def test_prompt_budget_thresholds_are_ratio_based() -> None:
    profile = ModelContextProfile(
        model="small",
        context_window_tokens=1000,
        default_output_tokens=0,
    )
    config = PromptBudgetConfig(
        warn_ratio=0.80,
        auto_compact_ratio=0.85,
        emergency_ratio=0.90,
        safety_margin_tokens=0,
    )

    def action(tokens: int) -> PromptBudgetAction:
        return decide_prompt_budget(
            estimate=PromptTokenEstimate(prompt_tokens=tokens, breakdown={}),
            profile=profile,
            config=config,
        ).action

    assert action(799) is PromptBudgetAction.OK
    assert action(800) is PromptBudgetAction.WARN
    assert action(850) is PromptBudgetAction.AUTO_COMPACT
    assert action(900) is PromptBudgetAction.EMERGENCY
