from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping
from collections.abc import Sequence

from openzyme_core import AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_DIGEST
from openzyme_core import AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_ID
from openzyme_core import AOX_SCIENTIFIC_FILE_ROLES
from openzyme_core import ScientificDeliverableFinalizationService
from openzyme_core import ScientificPublishedByteReader
from openzyme_core import ScientificPublishedFileResolver
from openzyme_core import ScientificRoleRequirement
from openzyme_core import aox_format_contract_digest
from openzyme_core import require_exact_aox_scientific_file_manifest
from openzyme_core import validate_aox_scientific_file_bytes
from openzyme_pipeline import aox_candidate
from openzyme_pipeline.aox_finalization import FINALIZATION_CALCULATION_ID
from openzyme_pipeline.aox_finalization import finalization_calculation_receipt
from openzyme_pipeline.aox_finalization import validate_installed_calculation_receipt


class AoxFileBundleFinalizationError(RuntimeError):
    error_code = "aox_file_bundle_finalization_rejected"


def _validate_nonempty_utf8(content: bytes) -> None:
    if not content:
        raise AoxFileBundleFinalizationError(
            "AOX scientific publication contains a zero-byte role"
        )
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AoxFileBundleFinalizationError(
            "AOX scientific publication contains non-UTF-8 bytes"
        ) from exc


@dataclass(slots=True)
class AoxFileBundleFinalizer:
    repositories: Any
    reader: ScientificPublishedByteReader

    def finalize(
        self,
        *,
        publication_id: str,
        attempt_id: str,
        selection_id: str,
        actor_ref: str,
        execution_fencing_token: int,
        producer_adoption_ids_by_role: dict[str, str],
        calculation_receipts: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        manifest = tuple(
            (entry.role, entry.path, entry.format_contract_id)
            for entry in AOX_SCIENTIFIC_FILE_ROLES
        )
        require_exact_aox_scientific_file_manifest(manifest)
        if set(producer_adoption_ids_by_role) != {
            entry.role for entry in AOX_SCIENTIFIC_FILE_ROLES
        }:
            raise AoxFileBundleFinalizationError(
                "AOX producer adoption map must name the exact 17 roles"
            )
        receipts = tuple(dict(item) for item in calculation_receipts)
        receipt_by_calculation = {
            str(item.get("calculation_id") or ""): item for item in receipts
        }
        if (
            len(receipt_by_calculation) != len(receipts)
            or receipt_by_calculation.get(FINALIZATION_CALCULATION_ID)
            != finalization_calculation_receipt()
        ):
            raise AoxFileBundleFinalizationError(
                "AOX finalization calculation receipt set is incomplete or conflicting"
            )
        if aox_candidate.CALCULATION_ID not in receipt_by_calculation:
            raise AoxFileBundleFinalizationError(
                "AOX finalization lacks the exact candidate calculation receipt"
            )
        for receipt in receipts:
            validate_installed_calculation_receipt(receipt)
        resolver = ScientificPublishedFileResolver(self.repositories, self.reader)
        resolved = {
            entry.path: resolver.resolve(
                publication_id=publication_id,
                path=entry.path,
            ).actual_bytes
            for entry in AOX_SCIENTIFIC_FILE_ROLES
        }
        validation = validate_aox_scientific_file_bytes(resolved)
        requirements = tuple(
            ScientificRoleRequirement(
                scientific_role=entry.role,
                path=entry.path,
                format_contract_id=entry.format_contract_id,
                format_contract_digest=aox_format_contract_digest(
                    entry.format_contract_id
                ),
                producer_adoption_id=producer_adoption_ids_by_role[entry.role],
                validate_bytes=_validate_nonempty_utf8,
            )
            for entry in AOX_SCIENTIFIC_FILE_ROLES
        )
        result = ScientificDeliverableFinalizationService(
            repositories=self.repositories,
            resolver=resolver,
        ).finalize(
            publication_id=publication_id,
            attempt_id=attempt_id,
            selection_id=selection_id,
            actor_ref=actor_ref,
            execution_fencing_token=execution_fencing_token,
            contract_id=AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_ID,
            contract_digest=AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_DIGEST,
            requirements=requirements,
        )
        return {
            "schema_version": "aox_scientific_file_bundle_result@1",
            "bundle": result.bundle.to_dict(),
            "validation_receipt": result.receipt.to_dict(),
            "deliverables": [ref.to_dict() for ref in result.refs],
            "scientific_validation": validation,
            "task_transition_performed": False,
            "attempt_transition_performed": False,
            "selection_transition_performed": False,
            "report_transition_performed": False,
            "campaign_decision_performed": False,
        }


__all__ = ["AoxFileBundleFinalizationError", "AoxFileBundleFinalizer"]
