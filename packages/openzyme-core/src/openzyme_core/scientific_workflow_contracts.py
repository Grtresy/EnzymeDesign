from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ScientificAttempt
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import ScientificChainSelection

from .mutation_authority import canonical_digest


SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC = "explicit_atomic_adoption"
SCIENTIFIC_SAME_ATTEMPT_REUSE_POLICY = "same_attempt_only"


class ScientificWorkflowContractError(RuntimeError):
    """A digest-bound workflow contract could not authorize the request."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = {
            "boundary": "scientific_workflow_contract",
            "disposition": "fail_closed",
            "mutation_applied": False,
            **({} if details is None else details),
        }


def _require_identifier(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain surrounding whitespace")


@dataclass(frozen=True, order=True, slots=True)
class ScientificOperationSignature:
    sdk_module: str
    function_name: str

    def __post_init__(self) -> None:
        _require_identifier("sdk_module", self.sdk_module)
        _require_identifier("function_name", self.function_name)

    def matches(self, operation: ControlledOperation) -> bool:
        return (
            operation.sdk_module == self.sdk_module
            and operation.function_name == self.function_name
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "sdk_module": self.sdk_module,
            "function_name": self.function_name,
        }


@dataclass(frozen=True, slots=True)
class ScientificWorkflowRolePolicy:
    role_id: str
    operation_signatures: tuple[ScientificOperationSignature, ...]
    cardinality: str

    def __post_init__(self) -> None:
        _require_identifier("role_id", self.role_id)
        _require_identifier("cardinality", self.cardinality)
        if not self.operation_signatures:
            raise ValueError("workflow role requires a closed operation signature")
        if len(set(self.operation_signatures)) != len(self.operation_signatures):
            raise ValueError("workflow role operation signatures must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "operation_signatures": [
                signature.to_dict()
                for signature in sorted(self.operation_signatures)
            ],
            "cardinality": self.cardinality,
        }


@dataclass(frozen=True, slots=True)
class ScientificWorkflowScopePolicy:
    scope: ScientificAttemptScope
    roles: tuple[ScientificWorkflowRolePolicy, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ScientificAttemptScope):
            raise TypeError("scope must be a ScientificAttemptScope")
        role_ids = [role.role_id for role in self.roles]
        if not role_ids:
            raise ValueError("workflow scope requires at least one role")
        if len(set(role_ids)) != len(role_ids):
            raise ValueError("workflow role ids must be unique within a scope")

    def role(self, role_id: str) -> ScientificWorkflowRolePolicy | None:
        return next(
            (role for role in self.roles if role.role_id == role_id),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.value,
            "roles": [
                role.to_dict()
                for role in sorted(self.roles, key=lambda item: item.role_id)
            ],
        }


@dataclass(frozen=True, slots=True)
class ScientificWorkflowContract:
    schema_id: str
    contract_id: str
    workflow_id: str
    scopes: tuple[ScientificWorkflowScopePolicy, ...]
    effect_adoption_policy: str
    same_attempt_reuse_policy: str
    projection_schema_version: str

    def __post_init__(self) -> None:
        _require_identifier("schema_id", self.schema_id)
        _require_identifier("contract_id", self.contract_id)
        _require_identifier("workflow_id", self.workflow_id)
        _require_identifier(
            "effect_adoption_policy",
            self.effect_adoption_policy,
        )
        _require_identifier(
            "same_attempt_reuse_policy",
            self.same_attempt_reuse_policy,
        )
        if (
            self.effect_adoption_policy
            != SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC
        ):
            raise ValueError(
                "unsupported scientific effect adoption policy"
            )
        if (
            self.same_attempt_reuse_policy
            != SCIENTIFIC_SAME_ATTEMPT_REUSE_POLICY
        ):
            raise ValueError(
                "unsupported scientific same-attempt reuse policy"
            )
        _require_identifier(
            "projection_schema_version",
            self.projection_schema_version,
        )
        scope_ids = [policy.scope for policy in self.scopes]
        if not scope_ids:
            raise ValueError("workflow contract requires at least one scope")
        if len(set(scope_ids)) != len(scope_ids):
            raise ValueError("workflow contract scopes must be unique")

    @property
    def canonical_preimage(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "contract_id": self.contract_id,
            "workflow_id": self.workflow_id,
            "scopes": [
                policy.to_dict()
                for policy in sorted(
                    self.scopes,
                    key=lambda item: item.scope.value,
                )
            ],
            "effect_adoption_policy": self.effect_adoption_policy,
            "same_attempt_reuse_policy": self.same_attempt_reuse_policy,
            "projection_schema_version": self.projection_schema_version,
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.canonical_preimage)

    def scope_policy(
        self,
        scope: ScientificAttemptScope,
    ) -> ScientificWorkflowScopePolicy:
        policy = next(
            (item for item in self.scopes if item.scope is scope),
            None,
        )
        if policy is None:
            raise ScientificWorkflowContractError(
                "workflow_contract_scope_unsupported",
                "attempt scope is not declared by the exact workflow contract",
                details={
                    "attempt_scope": scope.value,
                    "allowed_scopes": sorted(
                        item.scope.value for item in self.scopes
                    ),
                },
            )
        return policy

    def allowed_roles(
        self,
        scope: ScientificAttemptScope,
    ) -> tuple[str, ...]:
        policy = self.scope_policy(scope)
        return tuple(sorted(role.role_id for role in policy.roles))

    def compatible_roles(
        self,
        scope: ScientificAttemptScope,
        operation: ControlledOperation,
    ) -> tuple[str, ...]:
        return self.compatible_roles_for_signature(
            scope,
            sdk_module=operation.sdk_module,
            function_name=operation.function_name,
        )

    def compatible_roles_for_signature(
        self,
        scope: ScientificAttemptScope,
        *,
        sdk_module: str | None,
        function_name: str | None,
    ) -> tuple[str, ...]:
        policy = self.scope_policy(scope)
        return tuple(
            sorted(
                role.role_id
                for role in policy.roles
                if any(
                    signature.sdk_module == sdk_module
                    and signature.function_name == function_name
                    for signature in role.operation_signatures
                )
            )
        )

    def project(
        self,
        scope: ScientificAttemptScope,
    ) -> dict[str, Any]:
        policy = self.scope_policy(scope)
        return {
            "schema_version": self.projection_schema_version,
            "contract_schema_id": self.schema_id,
            "contract_id": self.contract_id,
            "workflow_id": self.workflow_id,
            "workflow_contract_digest": self.digest,
            "attempt_scope": scope.value,
            "roles": [
                role.to_dict()
                for role in sorted(
                    policy.roles,
                    key=lambda item: item.role_id,
                )
            ],
            "effect_adoption_policy": self.effect_adoption_policy,
            "same_attempt_reuse_policy": self.same_attempt_reuse_policy,
            "historical_read_only": False,
        }


@dataclass(frozen=True, slots=True)
class HistoricalScientificWorkflowContract:
    """Frozen identity and role reader for a pre-registry contract."""

    schema_id: str
    contract_id: str
    workflow_id: str
    workflow_contract_digest: str
    scope_roles: tuple[tuple[ScientificAttemptScope, tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        _require_identifier("schema_id", self.schema_id)
        _require_identifier("contract_id", self.contract_id)
        _require_identifier("workflow_id", self.workflow_id)
        _require_identifier(
            "workflow_contract_digest",
            self.workflow_contract_digest,
        )
        scopes = [scope for scope, _ in self.scope_roles]
        if not scopes or len(set(scopes)) != len(scopes):
            raise ValueError("historical workflow contract scopes must be unique")
        for scope, roles in self.scope_roles:
            if not isinstance(scope, ScientificAttemptScope):
                raise TypeError("historical scope must be a ScientificAttemptScope")
            if not roles or len(set(roles)) != len(roles):
                raise ValueError(
                    "historical workflow roles must be non-empty and unique"
                )
            for role in roles:
                _require_identifier("historical role", role)

    @property
    def digest(self) -> str:
        return self.workflow_contract_digest

    def project(
        self,
        scope: ScientificAttemptScope,
    ) -> dict[str, Any]:
        roles = next(
            (roles for item_scope, roles in self.scope_roles if item_scope is scope),
            None,
        )
        if roles is None:
            raise ScientificWorkflowContractError(
                "workflow_contract_scope_unsupported",
                "attempt scope is not declared by the historical workflow contract",
                details={"attempt_scope": scope.value},
            )
        return {
            "schema_version": "scientific_workflow_contract_projection@1",
            "contract_schema_id": self.schema_id,
            "contract_id": self.contract_id,
            "workflow_id": self.workflow_id,
            "workflow_contract_digest": self.digest,
            "attempt_scope": scope.value,
            "roles": [{"role_id": role} for role in sorted(roles)],
            "historical_read_only": True,
        }


ScientificWorkflowContractRecord = (
    ScientificWorkflowContract | HistoricalScientificWorkflowContract
)


@dataclass(frozen=True, slots=True)
class ScientificWorkflowContractRegistry:
    contracts: tuple[ScientificWorkflowContract, ...] = ()
    historical_contracts: tuple[HistoricalScientificWorkflowContract, ...] = ()

    def __post_init__(self) -> None:
        identities = [
            (contract.workflow_id, contract.digest)
            for contract in (*self.contracts, *self.historical_contracts)
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("workflow contract registry identities must be unique")
        contract_ids = [
            (contract.workflow_id, contract.contract_id)
            for contract in (*self.contracts, *self.historical_contracts)
        ]
        if len(set(contract_ids)) != len(contract_ids):
            raise ValueError("workflow contract ids must be unique per workflow")

    def resolve(
        self,
        *,
        workflow_id: str,
        workflow_contract_digest: str,
        for_new_attempt: bool = False,
    ) -> ScientificWorkflowContractRecord:
        contract = next(
            (
                item
                for item in self.contracts
                if item.workflow_id == workflow_id
                and item.digest == workflow_contract_digest
            ),
            None,
        )
        if contract is not None:
            return contract
        historical = next(
            (
                item
                for item in self.historical_contracts
                if item.workflow_id == workflow_id
                and item.digest == workflow_contract_digest
            ),
            None,
        )
        if historical is not None:
            if for_new_attempt:
                raise ScientificWorkflowContractError(
                    "workflow_contract_historical_read_only",
                    "historical workflow contract cannot authorize a new attempt",
                    details={
                        "workflow_id": workflow_id,
                        "workflow_contract_digest": workflow_contract_digest,
                        "contract_id": historical.contract_id,
                    },
                )
            return historical
        raise ScientificWorkflowContractError(
            "workflow_contract_digest_unsupported",
            "workflow id and digest do not resolve to an exact contract",
            details={
                "workflow_id": workflow_id,
                "workflow_contract_digest": workflow_contract_digest,
            },
        )

    def resolve_attempt(
        self,
        attempt: ScientificAttempt,
    ) -> ScientificWorkflowContractRecord:
        return self.resolve(
            workflow_id=attempt.workflow_id,
            workflow_contract_digest=attempt.workflow_contract_digest,
        )

    def compatible_roles(
        self,
        *,
        attempt: ScientificAttempt,
        operation: ControlledOperation,
    ) -> tuple[str, ...]:
        contract = self.resolve_attempt(attempt)
        if isinstance(contract, HistoricalScientificWorkflowContract):
            return ()
        return contract.compatible_roles(attempt.scope, operation)

    def validate_role(
        self,
        *,
        attempt: ScientificAttempt,
        selection: ScientificChainSelection,
        workflow_role: str,
        operation: ControlledOperation,
        execution: ControlledOperationExecution,
    ) -> None:
        contract = self.resolve_attempt(attempt)
        if isinstance(contract, HistoricalScientificWorkflowContract):
            raise ScientificWorkflowContractError(
                "workflow_contract_historical_read_only",
                "historical workflow contract cannot authorize selection mutation",
                details={
                    "contract_id": contract.contract_id,
                    "workflow_contract_digest": contract.digest,
                },
            )
        if (
            selection.attempt_id != attempt.attempt_id
            or selection.workflow_contract_digest != contract.digest
        ):
            raise ScientificWorkflowContractError(
                "workflow_contract_digest_mismatch",
                "selection does not bind the exact attempt workflow contract",
                details={
                    "attempt_id": attempt.attempt_id,
                    "selection_id": selection.selection_id,
                    "workflow_contract_digest": contract.digest,
                },
            )
        allowed_roles = contract.allowed_roles(attempt.scope)
        compatible_roles = contract.compatible_roles(
            attempt.scope,
            operation,
        )
        if workflow_role not in allowed_roles:
            raise ScientificWorkflowContractError(
                "workflow_role_invalid",
                "workflow role is not declared by the exact scope contract",
                details={
                    "workflow_role": workflow_role,
                    "attempt_scope": attempt.scope.value,
                    "allowed_roles": list(allowed_roles),
                    "compatible_roles": list(compatible_roles),
                },
            )
        if workflow_role not in compatible_roles:
            raise ScientificWorkflowContractError(
                "workflow_role_operation_kind_invalid",
                "operation does not implement the declared workflow role",
                details={
                    "workflow_role": workflow_role,
                    "attempt_scope": attempt.scope.value,
                    "allowed_roles": list(allowed_roles),
                    "compatible_roles": list(compatible_roles),
                    "operation_signature": {
                        "sdk_module": operation.sdk_module,
                        "function_name": operation.function_name,
                    },
                },
            )
        if (
            operation.session_id != attempt.session_id
            or operation.task_id != attempt.task_id
            or operation.lane_id != attempt.lane_id
            or not operation.logical_operation_key.strip()
            or execution.operation_id != operation.operation_id
            or execution.session_id != attempt.session_id
            or execution.task_id != attempt.task_id
            or execution.lane_id != attempt.lane_id
        ):
            raise ScientificWorkflowContractError(
                "workflow_role_operation_scope_invalid",
                "operation does not belong to the exact attempt task and lane",
                details={
                    "workflow_role": workflow_role,
                    "attempt_scope": attempt.scope.value,
                    "allowed_roles": list(allowed_roles),
                    "compatible_roles": list(compatible_roles),
                },
            )

    def project_attempt(
        self,
        attempt: ScientificAttempt,
    ) -> dict[str, Any]:
        return self.resolve_attempt(attempt).project(attempt.scope)


__all__ = [
    "HistoricalScientificWorkflowContract",
    "SCIENTIFIC_EFFECT_ADOPTION_POLICY_ATOMIC",
    "SCIENTIFIC_SAME_ATTEMPT_REUSE_POLICY",
    "ScientificOperationSignature",
    "ScientificWorkflowContract",
    "ScientificWorkflowContractError",
    "ScientificWorkflowContractRecord",
    "ScientificWorkflowContractRegistry",
    "ScientificWorkflowRolePolicy",
    "ScientificWorkflowScopePolicy",
]
