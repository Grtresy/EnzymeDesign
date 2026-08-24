from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import ClassVar

from .identity import canonical_sha256_digest
from .identity import canonical_string_tuple
from .identity import require_digest
from .identity import require_identifier


TOOL_EXPOSURE_DECISION_SCHEMA_VERSION = "tool_exposure_decision@1"
TOOL_EXPOSURE_SNAPSHOT_SCHEMA_VERSION = "tool_exposure_snapshot@1"
COMMAND_TOOL_EXPANSION_SCHEMA_VERSION = "command_tool_expansion@1"


class ToolExposure(StrEnum):
    DIRECT = "direct"
    DEFERRED = "deferred"
    HIDDEN = "hidden"


@dataclass(frozen=True, slots=True)
class ToolExposureDecision:
    SCHEMA_VERSION: ClassVar[str] = TOOL_EXPOSURE_DECISION_SCHEMA_VERSION

    tool_name: str
    exposure: ToolExposure
    reason_code: str

    def __post_init__(self) -> None:
        require_identifier(self.tool_name, field_name="tool_name")
        require_identifier(self.reason_code, field_name="reason_code")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "tool_name": self.tool_name,
            "exposure": self.exposure.value,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ToolExposureDecision":
        if set(payload) != {"schema_version", "tool_name", "exposure", "reason_code"} or payload.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("tool exposure decision has an invalid closed schema")
        return cls(
            tool_name=str(payload["tool_name"]),
            exposure=ToolExposure(str(payload["exposure"])),
            reason_code=str(payload["reason_code"]),
        )


@dataclass(frozen=True, slots=True)
class ToolExposureSnapshot:
    SCHEMA_VERSION: ClassVar[str] = TOOL_EXPOSURE_SNAPSHOT_SCHEMA_VERSION

    exposure_snapshot_id: str
    session_id: str
    agent_member_id: str
    turn_id: str
    subject_policy_digest: str
    declared_tool_catalog_digest: str
    capability_binding_digest: str
    affordance_snapshot_id: str
    affordance_snapshot_digest: str
    workflow_authority_id: str
    workflow_authority_epoch: int
    workflow_authority_digest: str
    catalog_tool_names: tuple[str, ...]
    decisions: tuple[ToolExposureDecision, ...]
    created_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "exposure_snapshot_id", "session_id", "agent_member_id", "turn_id",
            "affordance_snapshot_id", "workflow_authority_id", "created_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "subject_policy_digest", "declared_tool_catalog_digest",
            "capability_binding_digest", "affordance_snapshot_digest",
            "workflow_authority_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if not isinstance(self.workflow_authority_epoch, int) or isinstance(self.workflow_authority_epoch, bool) or self.workflow_authority_epoch < 1:
            raise ValueError("workflow_authority_epoch must be positive")
        catalog = canonical_string_tuple(
            self.catalog_tool_names,
            field_name="catalog_tool_names",
            allow_empty=False,
        )
        by_name = {decision.tool_name: decision for decision in self.decisions}
        if len(by_name) != len(self.decisions):
            raise ValueError("tool exposure decisions must be unique")
        if set(by_name) != set(catalog):
            raise ValueError("tool exposure policy must cover the exact declared catalog")
        object.__setattr__(self, "catalog_tool_names", catalog)
        object.__setattr__(self, "decisions", tuple(by_name[name] for name in catalog))

    @property
    def exposure_snapshot_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def names(self, exposure: ToolExposure) -> tuple[str, ...]:
        return tuple(
            decision.tool_name
            for decision in self.decisions
            if decision.exposure is exposure
        )

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "exposure_snapshot_id": self.exposure_snapshot_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "turn_id": self.turn_id,
            "subject_policy_digest": self.subject_policy_digest,
            "declared_tool_catalog_digest": self.declared_tool_catalog_digest,
            "capability_binding_digest": self.capability_binding_digest,
            "affordance_snapshot_id": self.affordance_snapshot_id,
            "affordance_snapshot_digest": self.affordance_snapshot_digest,
            "workflow_authority_id": self.workflow_authority_id,
            "workflow_authority_epoch": self.workflow_authority_epoch,
            "workflow_authority_digest": self.workflow_authority_digest,
            "catalog_tool_names": list(self.catalog_tool_names),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "created_at": self.created_at,
        }
        if include_digest:
            payload["exposure_snapshot_digest"] = self.exposure_snapshot_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ToolExposureSnapshot":
        value = dict(payload)
        supplied_digest = value.pop("exposure_snapshot_digest", None)
        expected = {
            "schema_version", "exposure_snapshot_id", "session_id",
            "agent_member_id", "turn_id", "subject_policy_digest",
            "declared_tool_catalog_digest", "capability_binding_digest",
            "affordance_snapshot_id", "affordance_snapshot_digest",
            "workflow_authority_id", "workflow_authority_epoch",
            "workflow_authority_digest", "catalog_tool_names", "decisions",
            "created_at",
        }
        if set(value) != expected or value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("tool exposure snapshot has an invalid closed schema")
        decisions_value = value["decisions"]
        if not isinstance(decisions_value, list) or any(not isinstance(item, Mapping) for item in decisions_value):
            raise ValueError("tool exposure decisions must be an array of objects")
        snapshot = cls(
            exposure_snapshot_id=str(value["exposure_snapshot_id"]),
            session_id=str(value["session_id"]), agent_member_id=str(value["agent_member_id"]),
            turn_id=str(value["turn_id"]), subject_policy_digest=str(value["subject_policy_digest"]),
            declared_tool_catalog_digest=str(value["declared_tool_catalog_digest"]),
            capability_binding_digest=str(value["capability_binding_digest"]),
            affordance_snapshot_id=str(value["affordance_snapshot_id"]),
            affordance_snapshot_digest=str(value["affordance_snapshot_digest"]),
            workflow_authority_id=str(value["workflow_authority_id"]),
            workflow_authority_epoch=int(value["workflow_authority_epoch"]),
            workflow_authority_digest=str(value["workflow_authority_digest"]),
            catalog_tool_names=tuple(str(item) for item in value["catalog_tool_names"]),
            decisions=tuple(ToolExposureDecision.from_dict(item) for item in decisions_value),
            created_at=str(value["created_at"]),
        )
        if supplied_digest is not None and supplied_digest != snapshot.exposure_snapshot_digest:
            raise ValueError("tool exposure snapshot digest mismatch")
        return snapshot


@dataclass(frozen=True, slots=True)
class CommandToolExpansion:
    SCHEMA_VERSION: ClassVar[str] = COMMAND_TOOL_EXPANSION_SCHEMA_VERSION

    expansion_id: str
    command_id: str
    session_id: str
    exposure_snapshot_id: str
    exposure_snapshot_digest: str
    workflow_authority_id: str
    workflow_authority_epoch: int
    workflow_authority_digest: str
    expansion_revision: int
    expanded_tool_names: tuple[str, ...]
    created_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "expansion_id", "command_id", "session_id", "exposure_snapshot_id",
            "workflow_authority_id", "created_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("exposure_snapshot_digest", "workflow_authority_digest"):
            require_digest(getattr(self, field_name), field_name=field_name)
        for field_name in ("workflow_authority_epoch", "expansion_revision"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be positive")
        object.__setattr__(self, "expanded_tool_names", canonical_string_tuple(
            self.expanded_tool_names,
            field_name="expanded_tool_names",
            allow_empty=False,
        ))

    @property
    def expansion_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "expansion_id": self.expansion_id,
            "command_id": self.command_id,
            "session_id": self.session_id,
            "exposure_snapshot_id": self.exposure_snapshot_id,
            "exposure_snapshot_digest": self.exposure_snapshot_digest,
            "workflow_authority_id": self.workflow_authority_id,
            "workflow_authority_epoch": self.workflow_authority_epoch,
            "workflow_authority_digest": self.workflow_authority_digest,
            "expansion_revision": self.expansion_revision,
            "expanded_tool_names": list(self.expanded_tool_names),
            "created_at": self.created_at,
        }
        if include_digest:
            payload["expansion_digest"] = self.expansion_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CommandToolExpansion":
        value = dict(payload)
        supplied_digest = value.pop("expansion_digest", None)
        expected = {
            "schema_version", "expansion_id", "command_id", "session_id",
            "exposure_snapshot_id", "exposure_snapshot_digest",
            "workflow_authority_id", "workflow_authority_epoch",
            "workflow_authority_digest", "expansion_revision",
            "expanded_tool_names", "created_at",
        }
        if set(value) != expected or value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("command tool expansion has an invalid closed schema")
        expansion = cls(
            expansion_id=str(value["expansion_id"]), command_id=str(value["command_id"]),
            session_id=str(value["session_id"]), exposure_snapshot_id=str(value["exposure_snapshot_id"]),
            exposure_snapshot_digest=str(value["exposure_snapshot_digest"]),
            workflow_authority_id=str(value["workflow_authority_id"]),
            workflow_authority_epoch=int(value["workflow_authority_epoch"]),
            workflow_authority_digest=str(value["workflow_authority_digest"]),
            expansion_revision=int(value["expansion_revision"]),
            expanded_tool_names=tuple(str(item) for item in value["expanded_tool_names"]),
            created_at=str(value["created_at"]),
        )
        if supplied_digest is not None and supplied_digest != expansion.expansion_digest:
            raise ValueError("command tool expansion digest mismatch")
        return expansion


def validate_command_tool_expansion(
    snapshot: ToolExposureSnapshot,
    expansion: CommandToolExpansion,
) -> None:
    if (
        expansion.exposure_snapshot_id != snapshot.exposure_snapshot_id
        or expansion.exposure_snapshot_digest != snapshot.exposure_snapshot_digest
        or expansion.workflow_authority_id != snapshot.workflow_authority_id
        or expansion.workflow_authority_epoch != snapshot.workflow_authority_epoch
        or expansion.workflow_authority_digest != snapshot.workflow_authority_digest
    ):
        raise ValueError("command tool expansion does not bind the exact exposure snapshot")
    if not set(expansion.expanded_tool_names).issubset(snapshot.names(ToolExposure.DEFERRED)):
        raise ValueError("command tool expansion may contain only exact Deferred tools")


__all__ = [
    "COMMAND_TOOL_EXPANSION_SCHEMA_VERSION",
    "TOOL_EXPOSURE_DECISION_SCHEMA_VERSION",
    "TOOL_EXPOSURE_SNAPSHOT_SCHEMA_VERSION",
    "CommandToolExpansion",
    "ToolExposure",
    "ToolExposureDecision",
    "ToolExposureSnapshot",
    "validate_command_tool_expansion",
]
