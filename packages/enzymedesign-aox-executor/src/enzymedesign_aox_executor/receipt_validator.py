from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .aox_finalization import validate_installed_calculation_receipt


@dataclass(frozen=True, slots=True)
class AoxExecutorCalculationReceiptValidator:
    """Validate receipts against this exact installed AOX executor build."""

    def validate_receipt(
        self,
        receipt: Mapping[str, object],
    ) -> Mapping[str, object]:
        return validate_installed_calculation_receipt(receipt)


__all__ = ["AoxExecutorCalculationReceiptValidator"]
