from __future__ import annotations

from dataclasses import dataclass

from enzymedesign_core import SequenceProviderApplication
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import CapabilityRequirement
from openzyme_extension_spi import CapabilityRequirementKind

from .sequence import parse_sequence_text


SEQUENCE_PLUGIN_ID = "enzymedesign.sequence.toolpack"
_ID = {"type": "string", "minLength": 1}
_SAFE_OUTPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["state", "fallback_performed", "task_finished"],
    "properties": {
        "state": _ID,
        "record_count": {"type": "integer", "minimum": 0, "maximum": 10_000},
        "records": {
            "type": "array",
            "maxItems": 10_000,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "record_id",
                    "description",
                    "sequence",
                    "length",
                    "sequence_digest",
                ],
                "properties": {
                    "record_id": _ID,
                    "description": {"type": "string"},
                    "sequence": {"type": "string", "minLength": 1},
                    "length": {"type": "integer", "minimum": 1},
                    "sequence_digest": {
                        "type": "string",
                        "pattern": "^sha256:[0-9a-f]{64}$",
                    },
                },
            },
        },
        "provider": _ID,
        "operation": _ID,
        "item_count": {"type": "integer", "minimum": 0, "maximum": 100},
        "workspace_relative_path": {"type": "string", "minLength": 1},
        "result_digest": {
            "type": "string",
            "pattern": "^sha256:[0-9a-f]{64}$",
        },
        "fallback_performed": {"const": False},
        "task_finished": {"const": False},
    },
}

SEQUENCE_PARSE_TOOL_SPEC = ToolSpec(
    tool_name="enzymedesign.sequence.parse",
    description="Parse bounded FASTA or plain sequence text without external I/O.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["format", "sequence_text"],
        "properties": {
            "format": {"enum": ["fasta", "plain"]},
            "sequence_text": {
                "type": "string",
                "minLength": 1,
                "maxLength": 12_000_000,
            },
        },
    },
    output_schema=_SAFE_OUTPUT,
)


def _provider_tool(
    name: str,
    description: str,
    properties: dict[str, JsonValue],
    required: tuple[str, ...],
) -> ToolSpec:
    return ToolSpec(
        tool_name=name,
        description=description,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": list(required),
            "properties": properties,
        },
        output_schema=_SAFE_OUTPUT,
        required_authorities=("ordinary_network",),
    )


UNIPROT_TOOL_SPEC = _provider_tool(
    "enzymedesign.uniprot.fetch",
    "Lookup metadata or fetch FASTA through the exact selected UniProt provider route.",
    {
        "operation": {"enum": ["lookup", "download_fasta"]},
        "accession": _ID,
        "output_path": {"type": ["string", "null"], "minLength": 1},
        "idempotency_key": _ID,
        "route_id": _ID,
    },
    ("operation", "accession", "idempotency_key", "route_id"),
)
RCSB_TOOL_SPEC = _provider_tool(
    "enzymedesign.rcsb.query",
    "Search metadata or fetch one structure through the exact selected RCSB provider route.",
    {
        "operation": {"enum": ["search", "download_structure"]},
        "query": {"type": ["string", "null"], "minLength": 1},
        "pdb_id": {"type": ["string", "null"], "minLength": 1},
        "file_format": {"enum": ["pdb", "cif"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "output_path": {"type": ["string", "null"], "minLength": 1},
        "idempotency_key": _ID,
        "route_id": _ID,
    },
    ("operation", "idempotency_key", "route_id"),
)
INTERPRO_TOOL_SPEC = _provider_tool(
    "enzymedesign.interpro.query",
    "Query annotations through the exact selected InterPro provider route.",
    {
        "accession": _ID,
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "idempotency_key": _ID,
        "route_id": _ID,
    },
    ("accession", "idempotency_key", "route_id"),
)

SEQUENCE_TOOL_SPECS = (
    INTERPRO_TOOL_SPEC,
    RCSB_TOOL_SPEC,
    SEQUENCE_PARSE_TOOL_SPEC,
    UNIPROT_TOOL_SPEC,
)
SEQUENCE_PROVIDER_REQUIREMENTS = (
    CapabilityRequirement(
        capability_id="enzymedesign.provider.interpro",
        contract_spec="@1",
        kind=CapabilityRequirementKind.EXTENSION,
        operations=("query", "reconcile"),
    ),
    CapabilityRequirement(
        capability_id="enzymedesign.provider.rcsb",
        contract_spec="@1",
        kind=CapabilityRequirementKind.EXTENSION,
        operations=("search", "download", "reconcile"),
    ),
    CapabilityRequirement(
        capability_id="enzymedesign.provider.uniprot",
        contract_spec="@1",
        kind=CapabilityRequirementKind.EXTENSION,
        operations=("lookup", "download", "reconcile"),
    ),
)
_REQUIREMENTS_BY_TOOL = {
    INTERPRO_TOOL_SPEC.tool_name: (SEQUENCE_PROVIDER_REQUIREMENTS[0],),
    RCSB_TOOL_SPEC.tool_name: (SEQUENCE_PROVIDER_REQUIREMENTS[1],),
    SEQUENCE_PARSE_TOOL_SPEC.tool_name: (),
    UNIPROT_TOOL_SPEC.tool_name: (SEQUENCE_PROVIDER_REQUIREMENTS[2],),
}


@dataclass(slots=True)
class SequenceToolRuntime:
    contract: ToolSpec
    application: SequenceProviderApplication | None = None
    owner_plugin_id: str = SEQUENCE_PLUGIN_ID

    @property
    def runtime_id(self) -> str:
        suffix = self.contract.tool_name.removeprefix("enzymedesign.").replace(".", "-")
        return f"{SEQUENCE_PLUGIN_ID}.{suffix}@1"

    @property
    def requirements(self) -> tuple[CapabilityRequirement, ...]:
        return _REQUIREMENTS_BY_TOOL[self.contract.tool_name]

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_name != self.contract.tool_name:
            return self._rejected(invocation, "sequence_tool_identity_invalid")
        try:
            if self.contract.tool_name == SEQUENCE_PARSE_TOOL_SPEC.tool_name:
                records = parse_sequence_text(
                    str(invocation.arguments["sequence_text"]),
                    format_name=str(invocation.arguments["format"]),
                )
                payload: dict[str, JsonValue] = {
                    "state": "parsed",
                    "records": [record.to_dict() for record in records],
                    "record_count": len(records),
                }
            else:
                if self.application is None:
                    raise ValueError("selected provider application is unavailable")
                payload = dict(self.application.invoke(invocation=invocation))
        except (KeyError, TypeError, ValueError) as exc:
            return self._rejected(invocation, "sequence_request_invalid", str(exc))
        payload.update({"fallback_performed": False, "task_finished": False})
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="completed",
            summary="Sequence capability completed without fallback.",
            payload=payload,
        )

    @staticmethod
    def _rejected(
        invocation: ToolInvocation,
        code: str,
        summary: str = "Sequence request rejected.",
    ) -> ToolResult:
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            status="rejected",
            summary=summary,
            payload={
                "mutation_applied": False,
                "fallback_performed": False,
                "task_finished": False,
            },
            error_code=code,
        )


def build_sequence_plugin_runtimes(
    *, application: SequenceProviderApplication | None = None
) -> tuple[SequenceToolRuntime, ...]:
    return tuple(SequenceToolRuntime(spec, application) for spec in SEQUENCE_TOOL_SPECS)


__all__ = [
    "INTERPRO_TOOL_SPEC",
    "RCSB_TOOL_SPEC",
    "SEQUENCE_PARSE_TOOL_SPEC",
    "SEQUENCE_PLUGIN_ID",
    "SEQUENCE_PROVIDER_REQUIREMENTS",
    "SEQUENCE_TOOL_SPECS",
    "UNIPROT_TOOL_SPEC",
    "SequenceProviderApplication",
    "SequenceToolRuntime",
    "build_sequence_plugin_runtimes",
]
