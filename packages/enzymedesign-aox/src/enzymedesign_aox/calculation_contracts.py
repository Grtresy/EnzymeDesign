from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


AOX_CANDIDATE_CALCULATION_ID = "aox_motif_candidate_filter@1"
AOX_FINALIZATION_CALCULATION_ID = "aox_final_deliverable_normalization@1"


class AoxCalculationReceiptValidationPort(Protocol):
    """Validate a receipt against the exact Distribution-selected AOX Driver."""

    def validate_receipt(
        self,
        receipt: Mapping[str, object],
    ) -> Mapping[str, object]: ...


__all__ = [
    "AOX_CANDIDATE_CALCULATION_ID",
    "AOX_FINALIZATION_CALCULATION_ID",
    "AoxCalculationReceiptValidationPort",
]
