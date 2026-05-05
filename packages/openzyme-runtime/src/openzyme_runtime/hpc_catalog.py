from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import HpcCatalogEntrySummary
from .seams import HpcCatalogQuery


def _catalog_root() -> Path:
    return Path(__file__).resolve().parent / "data" / "hpc_catalog"


class RepoBackedHpcCatalogProvider:
    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root or _catalog_root()
        self._entries = self._load_entries()

    def _load_entries(self) -> list[dict[str, Any]]:
        index_path = self._root / "index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        entries = payload.get("tools", [])
        if not isinstance(entries, list):
            raise ValueError("HPC catalog index must contain a 'tools' list.")
        return [dict(entry) for entry in entries]

    def search_catalog(self, query: HpcCatalogQuery) -> list[HpcCatalogEntrySummary]:
        query_text = query.query.strip().lower()
        requested_stage_tags = set(query.stage_tags)
        requested_capability_tags = set(query.capability_tags)
        results: list[HpcCatalogEntrySummary] = []
        for entry in self._entries:
            stage_tags = tuple(str(tag) for tag in entry.get("stage_tags", ()))
            capability_tags = tuple(str(tag) for tag in entry.get("capability_tags", ()))
            haystack = " ".join(
                [
                    str(entry.get("tool_id", "")),
                    str(entry.get("display_name", "")),
                    str(entry.get("summary", "")),
                    " ".join(stage_tags),
                    " ".join(capability_tags),
                ]
            ).lower()
            if query_text and query_text not in haystack:
                continue
            if requested_stage_tags and not requested_stage_tags.intersection(stage_tags):
                continue
            if requested_capability_tags and not requested_capability_tags.intersection(capability_tags):
                continue
            if query.execution_support and str(entry.get("execution_support")) != query.execution_support:
                continue
            results.append(
                HpcCatalogEntrySummary(
                    tool_id=str(entry["tool_id"]),
                    display_name=str(entry["display_name"]),
                    summary=str(entry["summary"]),
                    stage_tags=list(stage_tags),
                    capability_tags=list(capability_tags),
                    execution_support=str(entry.get("execution_support", "query_only")),  # type: ignore[arg-type]
                    skill_ref=str(entry["skill_ref"]),
                )
            )
        return results

    def get_entry(self, tool_id: str) -> dict[str, Any] | None:
        for entry in self._entries:
            if str(entry.get("tool_id")) == tool_id:
                return dict(entry)
        return None

    def read_skill(self, tool_id: str) -> str:
        entry = self.get_entry(tool_id)
        if entry is None:
            raise KeyError(f"Unknown HPC tool: {tool_id}")
        skill_path = self._root / str(entry["skill_ref"])
        return skill_path.read_text(encoding="utf-8")


__all__ = ["RepoBackedHpcCatalogProvider"]
