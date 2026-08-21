from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from openzyme_science import ScientificDeliverableFinalizationPort
from openzyme_science import ScientificPublishedFileReadPort

from .calculation_contracts import AoxCalculationReceiptValidationPort
from .file_bundle_finalizer import AoxFileBundleFinalizationError
from .file_bundle_finalizer import AoxFileBundleFinalizer


AOX_FINALIZATION_REQUEST_SCHEMA = "aox_scientific_file_finalize_request@1"
_REQUEST_FIELDS = {
    "schema_version",
    "publication_id",
    "attempt_id",
    "selection_id",
    "execution_fencing_token",
    "producer_adoption_ids_by_role",
    "calculation_receipts",
}


@dataclass(frozen=True, slots=True)
class AoxScientificDeliverableRequestHandler:
    calculation_receipts: AoxCalculationReceiptValidationPort

    def finalize_request(
        self,
        *,
        request: Mapping[str, object],
        actor_ref: str,
        published_files: ScientificPublishedFileReadPort,
        scientific_finalization: ScientificDeliverableFinalizationPort,
    ) -> Mapping[str, object]:
        body = dict(request)
        if (
            set(body) != _REQUEST_FIELDS
            or body.get("schema_version") != AOX_FINALIZATION_REQUEST_SCHEMA
        ):
            raise AoxFileBundleFinalizationError(
                "AOX scientific finalization request fields are closed"
            )
        adoptions = body["producer_adoption_ids_by_role"]
        receipts = body["calculation_receipts"]
        fence = body["execution_fencing_token"]
        if not isinstance(adoptions, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in adoptions.items()
        ):
            raise AoxFileBundleFinalizationError(
                "AOX producer adoption map must be an object of string identities"
            )
        if not isinstance(receipts, list) or not all(
            isinstance(item, dict) for item in receipts
        ):
            raise AoxFileBundleFinalizationError(
                "AOX calculation receipts must be an array of objects"
            )
        if isinstance(fence, bool) or not isinstance(fence, int) or fence < 1:
            raise AoxFileBundleFinalizationError(
                "AOX execution fencing token must be a positive integer"
            )
        return AoxFileBundleFinalizer(
            published_files=published_files,
            scientific_finalization=scientific_finalization,
            calculation_receipts=self.calculation_receipts,
        ).finalize(
            publication_id=str(body["publication_id"]),
            attempt_id=str(body["attempt_id"]),
            selection_id=str(body["selection_id"]),
            actor_ref=actor_ref,
            execution_fencing_token=fence,
            producer_adoption_ids_by_role=dict(adoptions),
            calculation_receipts=tuple(dict(item) for item in receipts),
        )


__all__ = [
    "AOX_FINALIZATION_REQUEST_SCHEMA",
    "AoxScientificDeliverableRequestHandler",
]
