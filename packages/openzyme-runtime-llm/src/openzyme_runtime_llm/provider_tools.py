from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from openzyme_contracts import ToolSpec


@dataclass(frozen=True, slots=True)
class ProviderToolCatalog:
    provider_tools: list[Any]
    canonical_to_provider: dict[str, str]
    provider_to_canonical: dict[str, str]

    @property
    def aliases(self) -> dict[str, str]:
        return {
            canonical: provider
            for canonical, provider in self.canonical_to_provider.items()
            if canonical != provider
        }

    def provider_messages(self, messages: list[Any]) -> list[Any]:
        if not self.aliases:
            return messages
        provider_messages = copy.deepcopy(messages)
        for message in provider_messages:
            _replace_tool_names_in_message(message, self.canonical_to_provider)
        return provider_messages

    def restore_response(self, response: Any) -> Any:
        if not self.aliases:
            return response
        _replace_tool_names_in_message(response, self.provider_to_canonical)
        return response


@dataclass(frozen=True, slots=True)
class ProviderToolAdapter:
    dotted_tool_name_aliasing: bool = False

    def prepare(self, tools: list[Any]) -> ProviderToolCatalog:
        provider_tools: list[Any] = []
        canonical_to_provider: dict[str, str] = {}
        provider_to_canonical: dict[str, str] = {}
        used_names = {
            name
            for tool in tools
            if (name := _canonical_tool_name(tool)) is not None
        }
        for index, tool in enumerate(tools, start=1):
            canonical_name = _canonical_tool_name(tool)
            provider_name = self._provider_name(
                canonical_name,
                used_names=used_names,
                suffix=index,
            )
            if canonical_name is not None:
                canonical_to_provider[canonical_name] = provider_name
                provider_to_canonical[provider_name] = canonical_name
                used_names.add(provider_name)
            provider_tools.append(_provider_tool(tool, provider_name))
        return ProviderToolCatalog(
            provider_tools=provider_tools,
            canonical_to_provider=canonical_to_provider,
            provider_to_canonical=provider_to_canonical,
        )

    def _provider_name(
        self,
        canonical_name: str | None,
        *,
        used_names: set[str],
        suffix: int,
    ) -> str | None:
        if (
            canonical_name is None
            or not self.dotted_tool_name_aliasing
            or "." not in canonical_name
        ):
            return canonical_name
        alias = canonical_name.replace(".", "_")
        if alias not in used_names or alias == canonical_name:
            return alias
        candidate = f"{alias}_{suffix}"
        counter = suffix
        while candidate in used_names:
            counter += 1
            candidate = f"{alias}_{counter}"
        return candidate


def openai_tool_from_spec(
    spec: ToolSpec,
    *,
    tool_name: str | None = None,
) -> dict[str, Any]:
    projected = spec.to_openai_tool()
    projected["function"]["name"] = tool_name or spec.tool_name
    return projected


def _canonical_tool_name(tool: Any) -> str | None:
    if isinstance(tool, ToolSpec):
        return tool.tool_name
    function = _tool_function_dict(tool)
    if function is None:
        return None
    name = function.get("name")
    return name if isinstance(name, str) else None


def _provider_tool(tool: Any, provider_name: str | None) -> Any:
    if isinstance(tool, ToolSpec):
        return openai_tool_from_spec(tool, tool_name=provider_name)
    if isinstance(tool, dict):
        provider_tool = copy.deepcopy(tool)
        function = _tool_function_dict(provider_tool)
        if function is not None and provider_name is not None:
            function["name"] = provider_name
        return provider_tool
    return tool


def _tool_function_dict(tool: Any) -> dict[str, Any] | None:
    if not isinstance(tool, dict):
        return None
    function = tool.get("function")
    return function if isinstance(function, dict) else None


def _replace_tool_names_in_message(message: Any, name_map: dict[str, str]) -> None:
    if isinstance(message, dict):
        _replace_tool_names_in_mapping(message, name_map)
        return
    for attr in ("tool_calls", "invalid_tool_calls", "content", "additional_kwargs"):
        if not hasattr(message, attr):
            continue
        try:
            value = getattr(message, attr)
        except Exception:
            continue
        _replace_tool_names_in_value(value, name_map)
    if hasattr(message, "name"):
        try:
            name = getattr(message, "name")
            if isinstance(name, str) and name in name_map:
                setattr(message, "name", name_map[name])
        except Exception:
            pass


def _replace_tool_names_in_value(value: Any, name_map: dict[str, str]) -> None:
    if isinstance(value, dict):
        _replace_tool_names_in_mapping(value, name_map)
        return
    if isinstance(value, list):
        for item in value:
            _replace_tool_names_in_value(item, name_map)


def _replace_tool_names_in_mapping(
    value: dict[str, Any],
    name_map: dict[str, str],
) -> None:
    name = value.get("name")
    if isinstance(name, str) and name in name_map:
        value["name"] = name_map[name]
    function = value.get("function")
    if isinstance(function, dict):
        function_name = function.get("name")
        if isinstance(function_name, str) and function_name in name_map:
            function["name"] = name_map[function_name]
    for key in ("tool_calls", "invalid_tool_calls", "content"):
        _replace_tool_names_in_value(value.get(key), name_map)
    additional_kwargs = value.get("additional_kwargs")
    if isinstance(additional_kwargs, dict):
        _replace_tool_names_in_mapping(additional_kwargs, name_map)


__all__ = [
    "ProviderToolAdapter",
    "ProviderToolCatalog",
    "openai_tool_from_spec",
]
