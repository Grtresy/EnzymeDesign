from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

InvocationMode = Literal["wrapper", "sif", "spack", "native"]


@dataclass(frozen=True, slots=True)
class FallbackReason:
    mode: InvocationMode
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"mode": self.mode, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class CompiledAdapterRun:
    adapter_id: str
    runspec: dict[str, Any]
    invocation_mode: InvocationMode
    fallback: list[FallbackReason]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "runspec": self.runspec,
            "invocation_mode": self.invocation_mode,
            "fallback": [step.to_dict() for step in self.fallback],
            "metadata": self.metadata,
        }
