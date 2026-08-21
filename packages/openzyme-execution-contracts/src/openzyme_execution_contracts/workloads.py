from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any
from typing import Mapping


WORKLOAD_SCHEMA = "execution_workload_spec@1"
ROUTE_SCHEMA = "execution_route_identity@1"
FAILURE_SCHEMA = "execution_wire_failure@1"
RESULT_SCHEMA = "execution_result_receipt@1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_CONTRACT = re.compile(r"[a-z][a-z0-9_.-]{1,127}@[1-9][0-9]*")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


class ExecutionWireContractError(ValueError):
    def __init__(self, error_code: str, *, field: str, detail: str) -> None:
        self.error_code = error_code
        self.field = field
        self.detail = detail
        super().__init__(f"{error_code}: field={field} detail={detail}")


def canonical_execution_wire_digest(value: object) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ExecutionWireContractError(
            "execution_wire_not_closed_json",
            field="payload",
            detail=exc.__class__.__name__,
        ) from exc
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _closed(
    value: object,
    *,
    fields: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ExecutionWireContractError(
            "execution_wire_not_object",
            field=label,
            detail=f"observed_type={type(value).__name__}",
        )
    observed = set(value)
    if observed != fields:
        raise ExecutionWireContractError(
            "execution_wire_fields_mismatch",
            field=label,
            detail=f"missing={sorted(fields - observed)!r} extra={sorted(observed - fields)!r}",
        )
    return dict(value)


def _identifier(field: str, value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ExecutionWireContractError(
            "execution_wire_field_invalid", field=field, detail="expected=safe_identifier"
        )
    return value


def _contract(field: str, value: object) -> str:
    if not isinstance(value, str) or _CONTRACT.fullmatch(value) is None:
        raise ExecutionWireContractError(
            "execution_wire_field_invalid", field=field, detail="expected=versioned_contract"
        )
    return value


def _digest(field: str, value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ExecutionWireContractError(
            "execution_wire_field_invalid", field=field, detail="expected=sha256_digest"
        )
    return value


def _oid(field: str, value: object) -> str:
    if not isinstance(value, str) or _OID.fullmatch(value) is None:
        raise ExecutionWireContractError(
            "execution_wire_field_invalid", field=field, detail="expected=git_object_id"
        )
    return value


def _relative_path(field: str, value: object, *, allow_dot: bool = True) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ExecutionWireContractError(
            "execution_wire_field_invalid", field=field, detail="expected=root_relative_path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or (not allow_dot and value == ".")
    ):
        raise ExecutionWireContractError(
            "execution_wire_field_invalid", field=field, detail="expected=root_relative_path"
        )
    return value


def _string_tuple(field: str, value: object, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ExecutionWireContractError(
            "execution_wire_field_invalid", field=field, detail="expected=closed_string_array"
        )
    result = tuple(value)
    if any(not isinstance(item, str) or not item or "\x00" in item for item in result):
        raise ExecutionWireContractError(
            "execution_wire_field_invalid", field=field, detail="expected=closed_string_array"
        )
    return result


@dataclass(frozen=True, slots=True)
class ExecutionRevisionInputRef:
    revision_id: str
    commit: str
    tree: str
    path: str
    content_digest: str

    @classmethod
    def from_dict(cls, value: object) -> "ExecutionRevisionInputRef":
        data = _closed(
            value,
            fields=frozenset({"revision_id", "commit", "tree", "path", "content_digest"}),
            label="inputs[]",
        )
        return cls(
            revision_id=_identifier("inputs[].revision_id", data["revision_id"]),
            commit=_oid("inputs[].commit", data["commit"]),
            tree=_oid("inputs[].tree", data["tree"]),
            path=_relative_path("inputs[].path", data["path"], allow_dot=False),
            content_digest=_digest("inputs[].content_digest", data["content_digest"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "revision_id": self.revision_id,
            "commit": self.commit,
            "tree": self.tree,
            "path": self.path,
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True, slots=True)
class ExecutionCapabilityRequirement:
    capability_id: str
    version_spec: str
    operations: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object) -> "ExecutionCapabilityRequirement":
        data = _closed(
            value,
            fields=frozenset({"capability_id", "version_spec", "operations"}),
            label="capability_requirements[]",
        )
        version_spec = data["version_spec"]
        if not isinstance(version_spec, str) or not version_spec or "\x00" in version_spec:
            raise ExecutionWireContractError(
                "execution_wire_field_invalid",
                field="capability_requirements[].version_spec",
                detail="expected=nonempty_version_spec",
            )
        return cls(
            capability_id=_identifier(
                "capability_requirements[].capability_id", data["capability_id"]
            ),
            version_spec=version_spec,
            operations=_string_tuple(
                "capability_requirements[].operations", data["operations"], nonempty=True
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "version_spec": self.version_spec,
            "operations": list(self.operations),
        }


@dataclass(frozen=True, slots=True)
class ExecutionResultContract:
    contract_id: str
    schema_digest: str
    result_root: str

    @classmethod
    def from_dict(cls, value: object) -> "ExecutionResultContract":
        data = _closed(
            value,
            fields=frozenset({"contract_id", "schema_digest", "result_root"}),
            label="result_contract",
        )
        return cls(
            contract_id=_contract("result_contract.contract_id", data["contract_id"]),
            schema_digest=_digest("result_contract.schema_digest", data["schema_digest"]),
            result_root=_relative_path(
                "result_contract.result_root", data["result_root"], allow_dot=False
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "schema_digest": self.schema_digest,
            "result_root": self.result_root,
        }


@dataclass(frozen=True, slots=True)
class ExecutionRouteIdentity:
    route_id: str
    target_id: str
    provider_id: str
    inventory_generation: int
    inventory_digest: str
    qualification_digest: str
    schema_version: str = ROUTE_SCHEMA

    @classmethod
    def from_dict(cls, value: object) -> "ExecutionRouteIdentity":
        data = _closed(
            value,
            fields=frozenset(
                {
                    "schema_version",
                    "route_id",
                    "target_id",
                    "provider_id",
                    "inventory_generation",
                    "inventory_digest",
                    "qualification_digest",
                }
            ),
            label="route_identity",
        )
        if data["schema_version"] != ROUTE_SCHEMA:
            raise ExecutionWireContractError(
                "execution_wire_schema_unsupported",
                field="route_identity.schema_version",
                detail=f"expected={ROUTE_SCHEMA}",
            )
        generation = data["inventory_generation"]
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ExecutionWireContractError(
                "execution_wire_field_invalid",
                field="route_identity.inventory_generation",
                detail="expected=positive_integer",
            )
        return cls(
            route_id=_identifier("route_identity.route_id", data["route_id"]),
            target_id=_identifier("route_identity.target_id", data["target_id"]),
            provider_id=_identifier("route_identity.provider_id", data["provider_id"]),
            inventory_generation=generation,
            inventory_digest=_digest(
                "route_identity.inventory_digest", data["inventory_digest"]
            ),
            qualification_digest=_digest(
                "route_identity.qualification_digest", data["qualification_digest"]
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "route_id": self.route_id,
            "target_id": self.target_id,
            "provider_id": self.provider_id,
            "inventory_generation": self.inventory_generation,
            "inventory_digest": self.inventory_digest,
            "qualification_digest": self.qualification_digest,
        }


@dataclass(frozen=True, slots=True)
class ExecutionResultReceipt:
    result_id: str
    invocation_id: str
    operation_id: str
    execution_id: str
    route_id: str
    workload_digest: str
    state: str
    result_contract_digest: str
    result_revision_id: str | None
    result_digest: str
    terminal_receipt_digest: str
    schema_version: str = RESULT_SCHEMA

    @classmethod
    def from_dict(cls, value: object) -> "ExecutionResultReceipt":
        data = _closed(
            value,
            fields=frozenset(
                {
                    "schema_version",
                    "result_id",
                    "invocation_id",
                    "operation_id",
                    "execution_id",
                    "route_id",
                    "workload_digest",
                    "state",
                    "result_contract_digest",
                    "result_revision_id",
                    "result_digest",
                    "terminal_receipt_digest",
                }
            ),
            label="result",
        )
        if data["schema_version"] != RESULT_SCHEMA:
            raise ExecutionWireContractError(
                "execution_wire_schema_unsupported",
                field="result.schema_version",
                detail=f"expected={RESULT_SCHEMA}",
            )
        state = data["state"]
        if state not in {"succeeded", "failed", "cancelled"}:
            raise ExecutionWireContractError(
                "execution_wire_field_invalid",
                field="result.state",
                detail="expected=terminal_state",
            )
        revision_id = data["result_revision_id"]
        if revision_id is not None:
            revision_id = _identifier("result.result_revision_id", revision_id)
        return cls(
            result_id=_identifier("result.result_id", data["result_id"]),
            invocation_id=_identifier("result.invocation_id", data["invocation_id"]),
            operation_id=_identifier("result.operation_id", data["operation_id"]),
            execution_id=_identifier("result.execution_id", data["execution_id"]),
            route_id=_identifier("result.route_id", data["route_id"]),
            workload_digest=_digest("result.workload_digest", data["workload_digest"]),
            state=state,
            result_contract_digest=_digest(
                "result.result_contract_digest", data["result_contract_digest"]
            ),
            result_revision_id=revision_id,
            result_digest=_digest("result.result_digest", data["result_digest"]),
            terminal_receipt_digest=_digest(
                "result.terminal_receipt_digest", data["terminal_receipt_digest"]
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "result_id": self.result_id,
            "invocation_id": self.invocation_id,
            "operation_id": self.operation_id,
            "execution_id": self.execution_id,
            "route_id": self.route_id,
            "workload_digest": self.workload_digest,
            "state": self.state,
            "result_contract_digest": self.result_contract_digest,
            "result_revision_id": self.result_revision_id,
            "result_digest": self.result_digest,
            "terminal_receipt_digest": self.terminal_receipt_digest,
        }


@dataclass(frozen=True, slots=True)
class ExecutionWorkloadSpec:
    workload_id: str
    workload_contract: str
    entry_point: str
    argv: tuple[str, ...]
    cwd: str
    resource_policy_digest: str
    environment_policy_digest: str
    inputs: tuple[ExecutionRevisionInputRef, ...]
    result_contract: ExecutionResultContract
    capability_requirements: tuple[ExecutionCapabilityRequirement, ...]
    workload_digest: str
    schema_version: str = WORKLOAD_SCHEMA

    @classmethod
    def from_dict(cls, value: object) -> "ExecutionWorkloadSpec":
        data = _closed(
            value,
            fields=frozenset(
                {
                    "schema_version",
                    "workload_id",
                    "workload_contract",
                    "entry_point",
                    "argv",
                    "cwd",
                    "resource_policy_digest",
                    "environment_policy_digest",
                    "inputs",
                    "result_contract",
                    "capability_requirements",
                    "workload_digest",
                }
            ),
            label="workload",
        )
        if data["schema_version"] != WORKLOAD_SCHEMA:
            raise ExecutionWireContractError(
                "execution_wire_schema_unsupported",
                field="workload.schema_version",
                detail=f"expected={WORKLOAD_SCHEMA}",
            )
        raw_inputs = data["inputs"]
        raw_requirements = data["capability_requirements"]
        if not isinstance(raw_inputs, list) or not raw_inputs:
            raise ExecutionWireContractError(
                "execution_wire_field_invalid", field="workload.inputs", detail="expected=nonempty_array"
            )
        if not isinstance(raw_requirements, list):
            raise ExecutionWireContractError(
                "execution_wire_field_invalid",
                field="workload.capability_requirements",
                detail="expected=array",
            )
        workload = cls(
            workload_id=_identifier("workload.workload_id", data["workload_id"]),
            workload_contract=_contract(
                "workload.workload_contract", data["workload_contract"]
            ),
            entry_point=_contract("workload.entry_point", data["entry_point"]),
            argv=_string_tuple("workload.argv", data["argv"], nonempty=True),
            cwd=_relative_path("workload.cwd", data["cwd"]),
            resource_policy_digest=_digest(
                "workload.resource_policy_digest", data["resource_policy_digest"]
            ),
            environment_policy_digest=_digest(
                "workload.environment_policy_digest", data["environment_policy_digest"]
            ),
            inputs=tuple(ExecutionRevisionInputRef.from_dict(item) for item in raw_inputs),
            result_contract=ExecutionResultContract.from_dict(data["result_contract"]),
            capability_requirements=tuple(
                ExecutionCapabilityRequirement.from_dict(item)
                for item in raw_requirements
            ),
            workload_digest=_digest("workload.workload_digest", data["workload_digest"]),
        )
        expected = canonical_execution_wire_digest(workload.identity_payload)
        if workload.workload_digest != expected:
            raise ExecutionWireContractError(
                "execution_wire_digest_mismatch",
                field="workload.workload_digest",
                detail=f"expected={expected}",
            )
        return workload

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workload_id": self.workload_id,
            "workload_contract": self.workload_contract,
            "entry_point": self.entry_point,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "resource_policy_digest": self.resource_policy_digest,
            "environment_policy_digest": self.environment_policy_digest,
            "inputs": [item.to_dict() for item in self.inputs],
            "result_contract": self.result_contract.to_dict(),
            "capability_requirements": [
                item.to_dict() for item in self.capability_requirements
            ],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "workload_digest": self.workload_digest}


@dataclass(frozen=True, slots=True)
class ExecutionWireFailure:
    error_code: str
    phase: str
    effect_certainty: str
    retryable: bool
    diagnostic_id: str
    schema_version: str = FAILURE_SCHEMA

    @classmethod
    def from_dict(cls, value: object) -> "ExecutionWireFailure":
        data = _closed(
            value,
            fields=frozenset(
                {
                    "schema_version",
                    "error_code",
                    "phase",
                    "effect_certainty",
                    "retryable",
                    "diagnostic_id",
                }
            ),
            label="failure",
        )
        if data["schema_version"] != FAILURE_SCHEMA:
            raise ExecutionWireContractError(
                "execution_wire_schema_unsupported",
                field="failure.schema_version",
                detail=f"expected={FAILURE_SCHEMA}",
            )
        certainty = data["effect_certainty"]
        if certainty not in {"no_effect", "dispatch_in_doubt", "settled"}:
            raise ExecutionWireContractError(
                "execution_wire_field_invalid",
                field="failure.effect_certainty",
                detail="expected=closed_effect_certainty",
            )
        retryable = data["retryable"]
        if not isinstance(retryable, bool):
            raise ExecutionWireContractError(
                "execution_wire_field_invalid", field="failure.retryable", detail="expected=boolean"
            )
        return cls(
            error_code=_identifier("failure.error_code", data["error_code"]),
            phase=_identifier("failure.phase", data["phase"]),
            effect_certainty=certainty,
            retryable=retryable,
            diagnostic_id=_identifier("failure.diagnostic_id", data["diagnostic_id"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "error_code": self.error_code,
            "phase": self.phase,
            "effect_certainty": self.effect_certainty,
            "retryable": self.retryable,
            "diagnostic_id": self.diagnostic_id,
        }


__all__ = [
    "FAILURE_SCHEMA",
    "RESULT_SCHEMA",
    "ROUTE_SCHEMA",
    "WORKLOAD_SCHEMA",
    "ExecutionCapabilityRequirement",
    "ExecutionResultContract",
    "ExecutionResultReceipt",
    "ExecutionRevisionInputRef",
    "ExecutionRouteIdentity",
    "ExecutionWireContractError",
    "ExecutionWireFailure",
    "ExecutionWorkloadSpec",
    "canonical_execution_wire_digest",
]
