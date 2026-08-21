from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class KernelContractError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})
        self.mutation_applied = False
        self.effect_certainty = "no_effect"
        self.fallback_performed = False


__all__ = ["KernelContractError"]
