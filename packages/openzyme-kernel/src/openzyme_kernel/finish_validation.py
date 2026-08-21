from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import EvidenceRef
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier
from openzyme_extension_spi import KernelEntitySnapshot
from openzyme_extension_spi import KernelQueryContext
from openzyme_extension_spi import TaskEvidenceValidation
from openzyme_extension_spi import TaskEvidenceValidator

from .errors import KernelContractError


@dataclass(frozen=True, slots=True)
class FinishValidatorBinding:
    """One exact validator selected by the pinned Session extension bundle."""

    owner_plugin_id: str
    validator: TaskEvidenceValidator

    def __post_init__(self) -> None:
        require_identifier(self.owner_plugin_id, field_name="owner_plugin_id")
        require_identifier(self.validator.validator_id, field_name="validator_id")


class FinishValidatorRegistry:
    """Closed, read-only registry used only during an explicit task.finish call."""

    def __init__(self, bindings: tuple[FinishValidatorBinding, ...] = ()) -> None:
        ordered = tuple(
            sorted(bindings, key=lambda item: item.validator.validator_id)
        )
        validator_ids = [item.validator.validator_id for item in ordered]
        if len(validator_ids) != len(set(validator_ids)):
            raise KernelContractError(
                "finish_validator_collision",
                "finish validator ids must be globally unique in one Session bundle",
                details={"validator_ids": validator_ids},
            )
        self._bindings = ordered
        self._by_id = {
            item.validator.validator_id: item for item in self._bindings
        }

    @classmethod
    def from_mounted(
        cls,
        mounted: tuple[tuple[str, TaskEvidenceValidator], ...],
    ) -> FinishValidatorRegistry:
        return cls(
            tuple(
                FinishValidatorBinding(owner_plugin_id=owner, validator=validator)
                for owner, validator in mounted
            )
        )

    @property
    def validator_ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)

    def validate(
        self,
        *,
        context: KernelQueryContext,
        task: KernelEntitySnapshot,
        evidence_refs: tuple[EvidenceRef, ...],
        required_validator_ids: tuple[str, ...],
    ) -> TaskEvidenceValidation:
        """Run exact validators without exposing a Core write handle."""

        required = tuple(sorted(required_validator_ids))
        if len(required) != len(set(required)):
            raise KernelContractError(
                "finish_validator_requirement_duplicate",
                "Task finish validator requirements must be unique",
                details={"task_id": task.entity.entity_id},
            )
        for validator_id in required:
            require_identifier(validator_id, field_name="required_validator_ids")

        missing = tuple(
            validator_id for validator_id in required if validator_id not in self._by_id
        )
        results: list[TaskEvidenceValidation] = []
        for validator_id in required:
            binding = self._by_id.get(validator_id)
            if binding is None:
                continue
            result = binding.validator.validate(context, task, evidence_refs)
            if result.validator_ids != (validator_id,):
                raise KernelContractError(
                    "finish_validator_identity_drift",
                    "finish validator returned an identity other than its mounted id",
                    details={
                        "mounted_validator_id": validator_id,
                        "returned_validator_ids": list(result.validator_ids),
                    },
                )
            results.append(result)

        rejection_codes = {
            code for result in results for code in result.rejection_codes
        }
        if missing:
            rejection_codes.add("required_finish_validator_unavailable")
        accepted = not missing and all(result.accepted for result in results)
        digest_payload = {
            "schema_version": "openzyme_finish_validation_aggregate@1",
            "session_id": context.session_id,
            "task_id": task.entity.entity_id,
            "task_state_version": task.entity.state_version,
            "required_validator_ids": list(required),
            "missing_validator_ids": list(missing),
            "evidence_digests": sorted(
                evidence.evidence_digest for evidence in evidence_refs
            ),
            "validation_digests": sorted(
                result.validation_digest for result in results
            ),
            "accepted": accepted,
            "rejection_codes": sorted(rejection_codes),
            "core_mutation_applied": False,
        }
        return TaskEvidenceValidation(
            accepted=accepted,
            validator_ids=required,
            rejection_codes=tuple(sorted(rejection_codes)),
            validation_digest=canonical_sha256_digest(digest_payload),
        )


__all__ = [
    "FinishValidatorBinding",
    "FinishValidatorRegistry",
]
