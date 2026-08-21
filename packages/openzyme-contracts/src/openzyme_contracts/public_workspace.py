from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .capabilities import ToolAffordanceSnapshot
from .identity import JsonValue
from .identity import canonical_sha256_digest
from .identity import freeze_json
from .identity import json_compatible
from .identity import require_digest
from .identity import require_identifier
from .release import LayeredReleaseIdentity


FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION = "file_workspace_public@2"
FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE = (
    "application/vnd.openzyme.file-workspace+json;version=2"
)
FILE_WORKSPACE_CORE_SECTION_FIELDS = frozenset(
    {
        "session",
        "tasks",
        "lanes",
        "agents",
        "protocol",
        "conversation",
        "approvals",
        "authority_leases",
        "capability_binding",
        "runtime",
        "workspace",
        "publications",
        "operations",
        "failures",
        "tool_reflection",
    }
)
FILE_WORKSPACE_CORE_SECTION_KINDS = {
    "session": "object",
    "tasks": "array",
    "lanes": "array",
    "agents": "array",
    "protocol": "object",
    "conversation": "object",
    "approvals": "array",
    "authority_leases": "array",
    "capability_binding": "object",
    "runtime": "object",
    "workspace": "object",
    "publications": "array",
    "operations": "object",
    "failures": "object",
    "tool_reflection": "object",
}
FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS = frozenset(
    {
        "agentcapabilitylease",
        "agentcapabilityleaseid",
        "agentcapabilityleases",
        "arti" + "fact",
        "arti" + "factcatalog",
        "arti" + "factindex",
        "arti" + "factkind",
        "arti" + "facts",
        "arti" + "factset",
        "alphafold",
        "aox",
        "compute",
        "docking",
        "fpocket",
        "hpc",
        "hpcstageref",
        "hpcworkspaces",
        "hmmer",
        "reports",
        "reportdrafts",
        "research",
        "researchfiles",
        "revisionexecutions",
        "scientificattempts",
        "scientificdeliverables",
        "scientificselections",
        "storageuri",
        "vina",
    }
)
FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_FRAGMENTS = frozenset(
    {
        "accesstoken",
        "credential",
        "hostpath",
        "loginalias",
        "lfsobjectlocator",
        "lfsobjectroot",
        "lfslocator",
        "privatekey",
        "privateref",
        "refreshtoken",
        "remoteroot",
        "repositoryroot",
        "schedulerhandle",
    }
)
FILE_WORKSPACE_TOOL_REFLECTION_FIELDS = frozenset(
    {
        "declared_tool_catalog_digest",
        "affordance_snapshot_digest",
        "capability_binding_digest",
        "available_tool_names",
        "affordances",
    }
)
FILE_WORKSPACE_TOOL_AFFORDANCE_FIELDS = frozenset(
    {
        "tool_name",
        "tool_contract_digest",
        "state",
        "required_authorities",
        "route_ids",
        "route_refs",
        "blockers",
    }
)
FILE_WORKSPACE_PUBLIC_TOOL_AFFORDANCE_STATES = frozenset(
    {
        "available",
        "available_with_approval",
        "blocked_dependency",
        "blocked_configuration",
        "blocked_qualification",
        "blocked_authority",
        "blocked_provisioning",
        "temporarily_unavailable",
    }
)
FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION,
        "media_type": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
        "root_fields": ["schema_version", "release", "core", "extensions"],
        "core_sections": dict(sorted(FILE_WORKSPACE_CORE_SECTION_KINDS.items())),
        "core_forbidden_field_tokens": sorted(
            FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS
        ),
        "core_forbidden_field_fragments": sorted(
            FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_FRAGMENTS
        ),
        "tool_reflection_fields": sorted(FILE_WORKSPACE_TOOL_REFLECTION_FIELDS),
        "tool_affordance_fields": sorted(FILE_WORKSPACE_TOOL_AFFORDANCE_FIELDS),
        "public_tool_affordance_states": sorted(
            FILE_WORKSPACE_PUBLIC_TOOL_AFFORDANCE_STATES
        ),
        "extension_fields": [
            "section_contract_digest",
            "payload",
            "next_cursor",
            "projection_digest",
        ],
    }
)


def _closed_json_mapping(
    value: Mapping[str, JsonValue],
    *,
    field_name: str,
) -> Mapping[str, JsonValue]:
    frozen = freeze_json(value, field_name=field_name)
    if not isinstance(frozen, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    return frozen


def _normalized_field_token(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _assert_core_public_value(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            token = _normalized_field_token(key)
            if token in FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS or any(
                fragment in token
                for fragment in FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_FRAGMENTS
            ):
                raise ValueError(
                    "file_workspace_public@2 core contains a forbidden public field; "
                    f"path={path}.{key}"
                )
            _assert_core_public_value(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_core_public_value(nested, path=f"{path}[{index}]")


def _assert_tool_reflection(payload: Mapping[str, JsonValue]) -> None:
    reflection = payload["tool_reflection"]
    binding = payload["capability_binding"]
    if not isinstance(reflection, Mapping) or not isinstance(binding, Mapping):
        raise ValueError("file_workspace_public@2 tool reflection is not structured")
    if set(reflection) != FILE_WORKSPACE_TOOL_REFLECTION_FIELDS:
        raise ValueError("file_workspace_public@2 tool reflection fields are closed")
    for field_name in (
        "declared_tool_catalog_digest",
        "affordance_snapshot_digest",
        "capability_binding_digest",
    ):
        require_digest(str(reflection[field_name]), field_name=field_name)
    binding_digest = binding.get("binding_digest")
    require_digest(str(binding_digest), field_name="binding_digest")
    if reflection["capability_binding_digest"] != binding_digest:
        raise ValueError("tool reflection belongs to another capability binding")
    names = reflection["available_tool_names"]
    affordances = reflection["affordances"]
    if not isinstance(names, (list, tuple)) or not isinstance(affordances, (list, tuple)):
        raise ValueError("tool reflection collections are invalid")
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("available tool names are invalid")
    observed_names: list[str] = []
    available_names: list[str] = []
    for affordance in affordances:
        if not isinstance(affordance, Mapping):
            raise ValueError("public tool affordance must be an object")
        if set(affordance) != FILE_WORKSPACE_TOOL_AFFORDANCE_FIELDS:
            raise ValueError("public tool affordance fields are closed")
        tool_name = affordance["tool_name"]
        state = affordance["state"]
        require_identifier(str(tool_name), field_name="tool_name")
        require_digest(
            str(affordance["tool_contract_digest"]),
            field_name="tool_contract_digest",
        )
        if state not in FILE_WORKSPACE_PUBLIC_TOOL_AFFORDANCE_STATES:
            raise ValueError("public tool affordance state is invalid")
        for collection_name in (
            "required_authorities",
            "route_ids",
            "route_refs",
            "blockers",
        ):
            if not isinstance(affordance[collection_name], (list, tuple)):
                raise ValueError("public tool affordance collection is invalid")
        blockers = affordance["blockers"]
        if state in {"available", "available_with_approval"}:
            if blockers:
                raise ValueError("available public tool affordance has blockers")
            available_names.append(str(tool_name))
        observed_names.append(str(tool_name))
    if len(set(observed_names)) != len(observed_names):
        raise ValueError("public tool affordances contain duplicate tool names")
    if list(names) != available_names:
        raise ValueError("available tool names differ from public affordances")


@dataclass(frozen=True, slots=True)
class FileWorkspaceToolReflection:
    declared_tool_catalog_digest: str
    affordance_snapshot: ToolAffordanceSnapshot

    def __post_init__(self) -> None:
        require_digest(
            self.declared_tool_catalog_digest,
            field_name="declared_tool_catalog_digest",
        )
        if (
            self.affordance_snapshot.declared_tool_catalog_digest
            != self.declared_tool_catalog_digest
        ):
            raise ValueError("affordance snapshot belongs to another declared catalog")
        if not self.affordance_snapshot.has_valid_digest():
            raise ValueError("affordance snapshot digest is invalid")

    def to_dict(self) -> dict[str, Any]:
        visible = [
            item.to_dict()
            for item in self.affordance_snapshot.affordances
            if item.state.value != "hidden"
        ]
        return {
            "declared_tool_catalog_digest": self.declared_tool_catalog_digest,
            "affordance_snapshot_digest": self.affordance_snapshot.snapshot_digest,
            "capability_binding_digest": (
                self.affordance_snapshot.capability_binding_digest
            ),
            "available_tool_names": list(
                self.affordance_snapshot.model_visible_tool_names
            ),
            "affordances": visible,
        }


@dataclass(frozen=True, slots=True)
class FileWorkspaceCoreProjectionV2:
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        observed = set(self.payload)
        if observed != FILE_WORKSPACE_CORE_SECTION_FIELDS:
            raise ValueError(
                "file_workspace_public@2 core section fields are closed; "
                f"missing={sorted(FILE_WORKSPACE_CORE_SECTION_FIELDS - observed)!r}, "
                f"unexpected={sorted(observed - FILE_WORKSPACE_CORE_SECTION_FIELDS)!r}"
            )
        for section_name, expected_kind in FILE_WORKSPACE_CORE_SECTION_KINDS.items():
            section = self.payload[section_name]
            if expected_kind == "object" and not isinstance(section, Mapping):
                raise ValueError(
                    "file_workspace_public@2 core section kind is invalid; "
                    f"section={section_name!r}, expected='object'"
                )
            if expected_kind == "array" and not isinstance(section, (list, tuple)):
                raise ValueError(
                    "file_workspace_public@2 core section kind is invalid; "
                    f"section={section_name!r}, expected='array'"
                )
        _assert_core_public_value(self.payload, path="core")
        _assert_tool_reflection(self.payload)
        object.__setattr__(
            self,
            "payload",
            _closed_json_mapping(self.payload, field_name="core"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return dict(json_compatible(self.payload))


@dataclass(frozen=True, slots=True)
class FileWorkspaceExtensionSectionV2:
    section_id: str
    section_contract_digest: str
    payload: Mapping[str, JsonValue]
    next_cursor: str | None
    projection_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.section_id, field_name="section_id")
        require_digest(
            self.section_contract_digest,
            field_name="section_contract_digest",
        )
        require_digest(self.projection_digest, field_name="projection_digest")
        if self.next_cursor is not None:
            require_identifier(self.next_cursor, field_name="next_cursor")
        object.__setattr__(
            self,
            "payload",
            _closed_json_mapping(
                self.payload,
                field_name=f"extensions.{self.section_id}.payload",
            ),
        )
        if self.projection_digest != self.observed_digest:
            raise ValueError("extension projection digest does not match its payload")

    @property
    def observed_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "section_id": self.section_id,
                "section_contract_digest": self.section_contract_digest,
                "payload": json_compatible(self.payload),
                "next_cursor": self.next_cursor,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_contract_digest": self.section_contract_digest,
            "payload": json_compatible(self.payload),
            "next_cursor": self.next_cursor,
            "projection_digest": self.projection_digest,
        }


@dataclass(frozen=True, slots=True)
class FileWorkspacePublicV2:
    release: LayeredReleaseIdentity
    core: FileWorkspaceCoreProjectionV2
    extensions: tuple[FileWorkspaceExtensionSectionV2, ...]

    def __post_init__(self) -> None:
        section_ids = [item.section_id for item in self.extensions]
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("extension projection section IDs must be unique")
        object.__setattr__(
            self,
            "extensions",
            tuple(sorted(self.extensions, key=lambda item: item.section_id)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION,
            "release": {
                **self.release.to_dict(),
                "release_digest": self.release.release_digest,
                "public_contract_digest": FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST,
            },
            "core": self.core.to_dict(),
            "extensions": {
                item.section_id: item.to_dict() for item in self.extensions
            },
        }

    @property
    def projection_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


__all__ = [
    "FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_FRAGMENTS",
    "FILE_WORKSPACE_CORE_FORBIDDEN_FIELD_TOKENS",
    "FILE_WORKSPACE_CORE_SECTION_FIELDS",
    "FILE_WORKSPACE_CORE_SECTION_KINDS",
    "FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST",
    "FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE",
    "FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION",
    "FileWorkspaceCoreProjectionV2",
    "FileWorkspaceExtensionSectionV2",
    "FileWorkspacePublicV2",
    "FileWorkspaceToolReflection",
]
