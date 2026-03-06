from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ConversionResult:
    output_path: str
    fmt_out: str
    input_path: str | None = None
    fmt_in: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "output_path": self.output_path,
            "fmt_out": self.fmt_out,
        }
        if self.input_path is not None:
            payload["input_path"] = self.input_path
        if self.fmt_in is not None:
            payload["fmt_in"] = self.fmt_in
        if self.details:
            payload["details"] = self.details
        return payload
