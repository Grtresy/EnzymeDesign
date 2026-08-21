from __future__ import annotations

from importlib.resources import files

import pytest

from enzymedesign_sequence_toolpack import SEQUENCE_COMPONENT_MANIFEST_DIGEST
from enzymedesign_sequence_toolpack import SEQUENCE_PARSE_TOOL_SPEC
from enzymedesign_sequence_toolpack import SEQUENCE_PROVIDER_REQUIREMENTS
from enzymedesign_sequence_toolpack import SEQUENCE_TOOL_SPECS
from enzymedesign_sequence_toolpack import SequenceToolRuntime
from enzymedesign_sequence_toolpack import locate_component_manifest
from enzymedesign_sequence_toolpack import parse_sequence_text
from openzyme_contracts import ToolInvocation
from openzyme_extension_spi import parse_component_manifest_json


def test_fasta_parser_is_bounded_deterministic_and_rejects_duplicate_ids() -> None:
    records = parse_sequence_text(
        ">seq-1 first\nACDE\nFG\n>seq-2\nMKT\n",
        format_name="fasta",
    )

    assert [item.record_id for item in records] == ["seq-1", "seq-2"]
    assert records[0].sequence == "ACDEFG"
    assert records[0].sequence_digest.startswith("sha256:")
    with pytest.raises(ValueError, match="unique"):
        parse_sequence_text(">same\nAAA\n>same\nCCC\n", format_name="fasta")


def test_parse_runtime_has_no_external_route_or_terminal_inference() -> None:
    runtime = SequenceToolRuntime(SEQUENCE_PARSE_TOOL_SPEC)
    result = runtime.invoke(
        ToolInvocation(
            call_id="call-1",
            tool_name=SEQUENCE_PARSE_TOOL_SPEC.tool_name,
            arguments={"format": "plain", "sequence_text": "MKT"},
            session_id="session-1",
            agent_member_id="agent-1",
        )
    )

    assert result.ok is True
    assert result.payload["record_count"] == 1
    assert result.payload["fallback_performed"] is False
    assert result.payload["task_finished"] is False


def test_provider_tools_require_exact_routes_without_fallback() -> None:
    by_capability = {
        item.capability_id: item for item in SEQUENCE_PROVIDER_REQUIREMENTS
    }

    assert set(by_capability) == {
        "enzymedesign.provider.interpro",
        "enzymedesign.provider.rcsb",
        "enzymedesign.provider.uniprot",
    }
    for spec in SEQUENCE_TOOL_SPECS:
        if spec is SEQUENCE_PARSE_TOOL_SPEC:
            continue
        assert "route_id" in spec.input_schema["required"]


def test_manifest_exactly_matches_runtime_contracts() -> None:
    locator = locate_component_manifest()
    manifest = parse_component_manifest_json(
        files(locator.resource_package)
        .joinpath(locator.resource_name)
        .read_text(encoding="utf-8")
    )

    assert manifest.manifest_digest == SEQUENCE_COMPONENT_MANIFEST_DIGEST
    assert locator.manifest_digest == SEQUENCE_COMPONENT_MANIFEST_DIGEST
    assert tuple(item.contract for item in manifest.tools) == SEQUENCE_TOOL_SPECS
    assert len({item.runtime_id for item in manifest.tools}) == len(manifest.tools)
    assert all(
        item.requires_explicit_route
        for item in manifest.tools
        if item.contract.tool_name != SEQUENCE_PARSE_TOOL_SPEC.tool_name
    )


def test_package_does_not_own_provider_or_platform_mechanisms() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in files("enzymedesign_sequence_toolpack").iterdir()
        if path.name.endswith(".py")
    )

    assert "urlopen" not in source
    assert "requests." not in source
    assert "openzyme_core" not in source
    assert "openzyme_host_api" not in source
    assert "paramiko" not in source
