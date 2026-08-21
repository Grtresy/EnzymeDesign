from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass

from openzyme_science import ScientificDeliverableFinalizationCommand
from openzyme_science import ScientificDeliverableFinalizationPort
from openzyme_science import ScientificPublishedFileReadPort
from openzyme_science import ScientificRoleFinalizationRequirement

from .calculation_contracts import AOX_CANDIDATE_CALCULATION_ID
from .calculation_contracts import AOX_FINALIZATION_CALCULATION_ID
from .calculation_contracts import AoxCalculationReceiptValidationPort
from .file_bundle_contract import AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_DIGEST
from .file_bundle_contract import AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_ID
from .file_bundle_contract import AOX_SCIENTIFIC_FILE_ROLES
from .file_bundle_contract import aox_format_contract_digest
from .file_bundle_contract import require_exact_aox_scientific_file_manifest
from .file_bundle_contract import validate_aox_scientific_file_bytes


class AoxFileBundleFinalizationError(RuntimeError):
    error_code = "aox_file_bundle_finalization_rejected"


@dataclass(slots=True)
class AoxFileBundleFinalizer:
    published_files: ScientificPublishedFileReadPort
    scientific_finalization: ScientificDeliverableFinalizationPort
    calculation_receipts: AoxCalculationReceiptValidationPort

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
        expected_roles = {entry.role for entry in AOX_SCIENTIFIC_FILE_ROLES}
        if set(producer_adoption_ids_by_role) != expected_roles:
            raise AoxFileBundleFinalizationError(
                "AOX producer adoption map must name the exact 17 roles"
            )
        receipts = tuple(dict(item) for item in calculation_receipts)
        receipt_by_calculation = {
            str(item.get("calculation_id") or ""): item for item in receipts
        }
        if len(receipt_by_calculation) != len(receipts):
            raise AoxFileBundleFinalizationError(
                "AOX finalization calculation receipt set is conflicting"
            )
        missing = {
            AOX_CANDIDATE_CALCULATION_ID,
            AOX_FINALIZATION_CALCULATION_ID,
        }.difference(receipt_by_calculation)
        if missing:
            raise AoxFileBundleFinalizationError(
                "AOX finalization calculation receipt set is incomplete"
            )
        for receipt in receipts:
            self.calculation_receipts.validate_receipt(receipt)

        resolved = {
            entry.path: self.published_files.read_bytes(
                publication_id=publication_id,
                path=entry.path,
            )
            for entry in AOX_SCIENTIFIC_FILE_ROLES
        }
        validation = validate_aox_scientific_file_bytes(resolved)
        requirements = tuple(
            ScientificRoleFinalizationRequirement(
                scientific_role=entry.role,
                path=entry.path,
                format_contract_id=entry.format_contract_id,
                format_contract_digest=aox_format_contract_digest(
                    entry.format_contract_id
                ),
                producer_adoption_id=producer_adoption_ids_by_role[entry.role],
            )
            for entry in AOX_SCIENTIFIC_FILE_ROLES
        )
        result = self.scientific_finalization.finalize(
            ScientificDeliverableFinalizationCommand(
                publication_id=publication_id,
                attempt_id=attempt_id,
                selection_id=selection_id,
                actor_ref=actor_ref,
                execution_fencing_token=execution_fencing_token,
                contract_id=AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_ID,
                contract_digest=AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_DIGEST,
                requirements=requirements,
            )
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
