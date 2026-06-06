from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import os
from typing import Any


class PromptBudgetAction(StrEnum):
    OK = "ok"
    WARN = "warn"
    AUTO_COMPACT = "auto_compact"
    EMERGENCY = "emergency"


@dataclass(frozen=True, slots=True)
class ModelContextProfile:
    model: str
    context_window_tokens: int
    default_output_tokens: int
    max_output_tokens: int | None = None
    profile_known: bool = True


@dataclass(frozen=True, slots=True)
class PromptBudgetConfig:
    warn_ratio: float = 0.80
    auto_compact_ratio: float = 0.85
    emergency_ratio: float = 0.90
    safety_margin_tokens: int = 4096


@dataclass(frozen=True, slots=True)
class PromptTokenEstimate:
    prompt_tokens: int
    breakdown: dict[str, int]
    tokenizer_calibrated: bool = False
    tokenizer_available: bool = False
    tokenizer_error: str | None = None


@dataclass(frozen=True, slots=True)
class PromptBudgetDecision:
    action: PromptBudgetAction
    prompt_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int
    total_budgeted_tokens: int
    context_window_tokens: int
    ratio: float
    profile: ModelContextProfile
    config: PromptBudgetConfig
    breakdown: dict[str, int]
    tokenizer_calibrated: bool = False
    tokenizer_available: bool = False
    tokenizer_error: str | None = None

    @property
    def should_warn(self) -> bool:
        return self.action in {
            PromptBudgetAction.WARN,
            PromptBudgetAction.AUTO_COMPACT,
            PromptBudgetAction.EMERGENCY,
        }


_GLM_51_PROFILE = ModelContextProfile(
    model="glm-5.1",
    context_window_tokens=200_000,
    default_output_tokens=65_536,
    max_output_tokens=131_072,
)
_UNKNOWN_FALLBACK_CONTEXT = 32_768
_UNKNOWN_FALLBACK_OUTPUT = 4_096


def _env_int(name: str) -> int | None:
    value = os.getenv(name)
    if value in {None, ""}:
        return None
    return int(str(value))


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value in {None, ""}:
        return default
    return float(str(value))


def prompt_budget_config_from_env() -> PromptBudgetConfig:
    return PromptBudgetConfig(
        warn_ratio=_env_float("OPENZYME_LLM_CONTEXT_WARN_RATIO", 0.80),
        auto_compact_ratio=_env_float("OPENZYME_LLM_CONTEXT_AUTO_COMPACT_RATIO", 0.85),
        emergency_ratio=_env_float("OPENZYME_LLM_CONTEXT_EMERGENCY_RATIO", 0.90),
    )


def model_context_profile_from_env_or_factory(model_factory: Any | None) -> ModelContextProfile:
    model = str(getattr(model_factory, "model", "") or os.getenv("OPENZYME_LLM_MODEL") or "unknown")
    context_override = _env_int("OPENZYME_LLM_CONTEXT_WINDOW_TOKENS")
    output_override = _env_int("OPENZYME_LLM_DEFAULT_OUTPUT_TOKENS")
    factory_context = getattr(model_factory, "context_window_tokens", None)
    factory_output = getattr(model_factory, "default_output_tokens", None)
    context_window = context_override or (int(factory_context) if factory_context else None)
    default_output = output_override or (int(factory_output) if factory_output else None)
    if model.lower() == "glm-5.1" or model.lower().startswith("glm-5.1"):
        return ModelContextProfile(
            model=model,
            context_window_tokens=context_window or _GLM_51_PROFILE.context_window_tokens,
            default_output_tokens=default_output or _GLM_51_PROFILE.default_output_tokens,
            max_output_tokens=_GLM_51_PROFILE.max_output_tokens,
            profile_known=True,
        )
    if context_window is not None:
        return ModelContextProfile(
            model=model,
            context_window_tokens=context_window,
            default_output_tokens=default_output or _UNKNOWN_FALLBACK_OUTPUT,
            max_output_tokens=None,
            profile_known=False,
        )
    return ModelContextProfile(
        model=model,
        context_window_tokens=_UNKNOWN_FALLBACK_CONTEXT,
        default_output_tokens=default_output or _UNKNOWN_FALLBACK_OUTPUT,
        max_output_tokens=None,
        profile_known=False,
    )


def _json_size_tokens(value: Any) -> int:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return max(1, (len(text) + 3) // 4)


class PromptTokenEstimator:
    def estimate(
        self,
        *,
        system_prompt: str,
        messages: list[Any],
        tools: list[Any],
        tool_observations: list[Any] | None = None,
        tokenizer_result: dict[str, Any] | None = None,
    ) -> PromptTokenEstimate:
        breakdown = {
            "system_prompt": max(1, (len(system_prompt) + 3) // 4),
            "messages": _json_size_tokens(messages),
            "tools": _json_size_tokens(tools),
            "tool_observations": _json_size_tokens(tool_observations or []),
            "message_overhead": max(0, 4 * (len(messages) + 1)),
            "tool_overhead": max(0, 8 * len(tools)),
        }
        local_prompt_tokens = sum(breakdown.values())
        if tokenizer_result and tokenizer_result.get("available"):
            prompt_tokens = tokenizer_result.get("prompt_tokens")
            if isinstance(prompt_tokens, int) and prompt_tokens > 0:
                breakdown["provider_tokenizer"] = prompt_tokens
                return PromptTokenEstimate(
                    prompt_tokens=prompt_tokens,
                    breakdown=breakdown,
                    tokenizer_calibrated=True,
                    tokenizer_available=True,
                )
        return PromptTokenEstimate(
            prompt_tokens=local_prompt_tokens,
            breakdown=breakdown,
            tokenizer_calibrated=False,
            tokenizer_available=bool(tokenizer_result and tokenizer_result.get("available")),
            tokenizer_error=None if not tokenizer_result else tokenizer_result.get("error"),
        )


def decide_prompt_budget(
    *,
    estimate: PromptTokenEstimate,
    profile: ModelContextProfile,
    config: PromptBudgetConfig | None = None,
) -> PromptBudgetDecision:
    config = config or PromptBudgetConfig()
    reserved_output_tokens = profile.default_output_tokens
    total = estimate.prompt_tokens + reserved_output_tokens + config.safety_margin_tokens
    ratio = total / profile.context_window_tokens
    if ratio >= config.emergency_ratio:
        action = PromptBudgetAction.EMERGENCY
    elif ratio >= config.auto_compact_ratio:
        action = PromptBudgetAction.AUTO_COMPACT
    elif ratio >= config.warn_ratio:
        action = PromptBudgetAction.WARN
    else:
        action = PromptBudgetAction.OK
    return PromptBudgetDecision(
        action=action,
        prompt_tokens=estimate.prompt_tokens,
        reserved_output_tokens=reserved_output_tokens,
        safety_margin_tokens=config.safety_margin_tokens,
        total_budgeted_tokens=total,
        context_window_tokens=profile.context_window_tokens,
        ratio=ratio,
        profile=profile,
        config=config,
        breakdown=estimate.breakdown,
        tokenizer_calibrated=estimate.tokenizer_calibrated,
        tokenizer_available=estimate.tokenizer_available,
        tokenizer_error=estimate.tokenizer_error,
    )


def estimate_and_decide_prompt_budget(
    *,
    system_prompt: str,
    messages: list[Any],
    tools: list[Any],
    model_factory: Any | None = None,
    tokenizer_result: dict[str, Any] | None = None,
    config: PromptBudgetConfig | None = None,
) -> PromptBudgetDecision:
    estimate = PromptTokenEstimator().estimate(
        system_prompt=system_prompt,
        messages=messages,
        tools=tools,
        tokenizer_result=tokenizer_result,
    )
    return decide_prompt_budget(
        estimate=estimate,
        profile=model_context_profile_from_env_or_factory(model_factory),
        config=config or prompt_budget_config_from_env(),
    )


__all__ = [
    "ModelContextProfile",
    "PromptBudgetAction",
    "PromptBudgetConfig",
    "PromptBudgetDecision",
    "PromptTokenEstimate",
    "PromptTokenEstimator",
    "decide_prompt_budget",
    "estimate_and_decide_prompt_budget",
    "model_context_profile_from_env_or_factory",
    "prompt_budget_config_from_env",
]
