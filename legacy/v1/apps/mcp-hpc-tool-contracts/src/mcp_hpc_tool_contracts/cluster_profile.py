from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib

from .constants import ADAPTER_DEFAULT_MODES


@dataclass(frozen=True, slots=True)
class AdapterProfile:
    mode: str = "sif"
    partition: str | None = None
    gpus: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def resource_overrides(self) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        if self.partition is not None:
            overrides["partition"] = self.partition
        if self.gpus is not None:
            overrides["gpus"] = self.gpus
        return overrides


@dataclass(frozen=True, slots=True)
class ClusterProfile:
    adapters: dict[str, AdapterProfile] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "ClusterProfile":
        return cls(adapters={})

    @classmethod
    def from_toml(cls, path: str | Path) -> "ClusterProfile":
        raw = tomllib.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        return cls._from_raw(raw)

    @classmethod
    def _from_raw(cls, raw: dict[str, Any]) -> "ClusterProfile":
        adapters: dict[str, AdapterProfile] = {}
        for adapter_id, section in raw.get("adapters", {}).items():
            gpus_raw = section.get("gpus")
            known_keys = {"mode", "partition", "gpus"}
            extra = {k: v for k, v in section.items() if k not in known_keys}
            adapters[adapter_id] = AdapterProfile(
                mode=str(section.get("mode", "sif")),
                partition=(
                    str(section["partition"]) if section.get("partition") else None
                ),
                gpus=int(gpus_raw) if gpus_raw is not None else None,
                extra=extra,
            )
        return cls(adapters=adapters)

    def mode_for(self, adapter_id: str) -> str:
        profile = self.adapters.get(adapter_id)
        return profile.mode if profile else ADAPTER_DEFAULT_MODES.get(adapter_id, "sif")

    def resource_overrides_for(self, adapter_id: str) -> dict[str, Any]:
        profile = self.adapters.get(adapter_id)
        return profile.resource_overrides() if profile else {}

    def extra_params_for(self, adapter_id: str) -> dict[str, Any]:
        profile = self.adapters.get(adapter_id)
        return dict(profile.extra) if profile else {}
