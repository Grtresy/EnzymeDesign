from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


def _default_catalog_root() -> Path:
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "packages" / "openzyme-tools" / "src" / "openzyme_tools" / "data" / "hpc_catalog"


def _extract_section_lines(markdown: str, heading: str) -> tuple[str, ...]:
    marker = f"## {heading}"
    if marker not in markdown:
        return ()
    tail = markdown.split(marker, maxsplit=1)[1]
    lines: list[str] = []
    for raw_line in tail.splitlines()[1:]:
        if raw_line.startswith("## "):
            break
        line = raw_line.strip()
        if line.startswith("- "):
            lines.append(line[2:].strip())
    return tuple(lines)


def _extract_example(markdown: str) -> dict[str, Any]:
    marker = "## Example Invocation Shape"
    if marker not in markdown:
        return {}
    tail = markdown.split(marker, maxsplit=1)[1]
    code_lines: list[str] = []
    in_block = False
    for raw_line in tail.splitlines()[1:]:
        if raw_line.startswith("## "):
            break
        if raw_line.startswith("```"):
            if not in_block:
                in_block = True
                continue
            break
        if in_block:
            code_lines.append(raw_line)
    if not code_lines:
        return {}
    try:
        return dict(json.loads("\n".join(code_lines)))
    except json.JSONDecodeError:
        return {}


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    skill_key: str
    title: str
    summary: str
    stage_tags: tuple[str, ...] = ()
    capability_tags: tuple[str, ...] = ()
    execution_support: str = "query_only"
    skill_ref: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "skill_key": self.skill_key,
            "title": self.title,
            "summary": self.summary,
            "stage_tags": list(self.stage_tags),
            "capability_tags": list(self.capability_tags),
            "execution_support": self.execution_support,
            "skill_ref": self.skill_ref,
        }


@dataclass(frozen=True, slots=True)
class SkillDocument:
    descriptor: SkillDescriptor
    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    failure_signatures: tuple[str, ...] = ()
    example_invocation_shape: dict[str, Any] | None = None
    raw_markdown: str = ""

    @property
    def skill_key(self) -> str:
        return self.descriptor.skill_key

    def to_dict(self) -> dict[str, object]:
        return {
            "descriptor": self.descriptor.to_dict(),
            "required_inputs": list(self.required_inputs),
            "optional_inputs": list(self.optional_inputs),
            "outputs": list(self.outputs),
            "failure_signatures": list(self.failure_signatures),
            "example_invocation_shape": dict(self.example_invocation_shape or {}),
            "raw_markdown": self.raw_markdown,
        }


class SkillRegistry:
    def __init__(self, *, catalog_root: Path | None = None) -> None:
        self._catalog_root = catalog_root or _default_catalog_root()
        self._descriptors = self._load_descriptors()
        self._cache: dict[str, SkillDocument] = {}

    def _read_index_payload(self) -> dict[str, Any]:
        index_path = self._catalog_root / "index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("skill catalog index must be a JSON object")
        return payload

    def _read_skill_markdown(self, descriptor: SkillDescriptor) -> str:
        skill_path = self._catalog_root / descriptor.skill_ref
        return skill_path.read_text(encoding="utf-8")

    def _load_descriptors(self) -> tuple[SkillDescriptor, ...]:
        payload = self._read_index_payload()
        entries = payload.get("tools", [])
        if not isinstance(entries, list):
            raise ValueError("skill catalog index must contain a 'tools' list")
        descriptors: list[SkillDescriptor] = []
        for entry in entries:
            descriptors.append(
                SkillDescriptor(
                    skill_key=str(entry["tool_id"]),
                    title=str(entry.get("display_name") or entry["tool_id"]),
                    summary=str(entry.get("summary") or ""),
                    stage_tags=tuple(str(tag) for tag in entry.get("stage_tags", ())),
                    capability_tags=tuple(str(tag) for tag in entry.get("capability_tags", ())),
                    execution_support=str(entry.get("execution_support", "query_only")),
                    skill_ref=str(entry["skill_ref"]),
                )
            )
        return tuple(descriptors)

    def list_skills(self) -> tuple[SkillDescriptor, ...]:
        return self._descriptors

    def get_descriptor(self, skill_key: str) -> SkillDescriptor | None:
        for descriptor in self._descriptors:
            if descriptor.skill_key == skill_key:
                return descriptor
        return None

    def load_skill(self, skill_key: str) -> SkillDocument:
        cached = self._cache.get(skill_key)
        if cached is not None:
            return cached
        descriptor = self.get_descriptor(skill_key)
        if descriptor is None:
            raise KeyError(f"unknown skill: {skill_key}")
        markdown = self._read_skill_markdown(descriptor)
        document = SkillDocument(
            descriptor=descriptor,
            required_inputs=_extract_section_lines(markdown, "Required Inputs"),
            optional_inputs=_extract_section_lines(markdown, "Optional Inputs"),
            outputs=_extract_section_lines(markdown, "Outputs"),
            failure_signatures=_extract_section_lines(markdown, "Failure Signatures"),
            example_invocation_shape=_extract_example(markdown),
            raw_markdown=markdown,
        )
        self._cache[skill_key] = document
        return document

    def load_skills(self, skill_keys: tuple[str, ...] | list[str]) -> tuple[SkillDocument, ...]:
        return tuple(self.load_skill(skill_key) for skill_key in skill_keys)


def register_skill_tools(registry: Any) -> None:
    from .harness import SessionRuntimeContext
    from .harness import ToolInvocation
    from .harness import ToolResult

    def list_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        descriptors = [descriptor.to_dict() for descriptor in context.skill_registry.list_skills()]
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(descriptors, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )

    def load_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        skill_key = str(invocation.arguments["skill_key"])
        document = context.skill_registry.load_skill(skill_key)
        context.add_skill_keys((skill_key,))
        context.refresh_restore_context()
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=document.raw_markdown,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )

    registry.register("skill.list", list_handler)
    registry.register("skill.load", load_handler)


__all__ = ["SkillDescriptor", "SkillDocument", "SkillRegistry", "register_skill_tools"]
