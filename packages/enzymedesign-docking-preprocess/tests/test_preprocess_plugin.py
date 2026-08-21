from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import pytest

from enzymedesign_docking_preprocess import PREPROCESS_COMPONENT_MANIFEST_DIGEST
from enzymedesign_docking_preprocess import PREPROCESS_TOOL_SPEC
from enzymedesign_docking_preprocess import PreprocessError
from enzymedesign_docking_preprocess import build_preprocess_plugin_runtime_surfaces
from enzymedesign_docking_preprocess import convert_format
from enzymedesign_docking_preprocess import locate_component_manifest
from enzymedesign_docking_preprocess import prepare_ligand
from enzymedesign_docking_preprocess import prepare_receptor
from openzyme_contracts import ToolInvocation
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import parse_component_manifest_json


PDB_TEXT = """\
ATOM      1  N   GLY A   1      11.104  13.207   9.541  1.00 20.00           N
ATOM      2  CA  GLY A   1      12.560  13.164   9.650  1.00 20.00           C
END
"""
DIGEST = "sha256:" + "1" * 64


def _manifest() -> PluginManifest:
    locator = locate_component_manifest()
    parsed = parse_component_manifest_json(
        files(locator.resource_package)
        .joinpath(locator.resource_name)
        .read_text(encoding="utf-8")
    )
    assert isinstance(parsed, PluginManifest)
    return parsed


def test_preprocess_manifest_owns_tool_and_chemical_qualification() -> None:
    manifest = _manifest()

    assert manifest.manifest_digest == PREPROCESS_COMPONENT_MANIFEST_DIGEST
    assert [item.contract.tool_name for item in manifest.tools] == [
        "enzymedesign.docking.preprocess"
    ]
    assert {item.capability_id for item in manifest.requires} == {
        "software.meeko",
        "software.openbabel",
        "software.rdkit",
    }
    assert all(
        item.kind is CapabilityRequirementKind.RESOURCE
        for item in manifest.requires
    )
    assert {item.capability_id for item in manifest.qualification_specs} == {
        "software.meeko",
        "software.openbabel",
        "software.rdkit",
    }
    assert PREPROCESS_TOOL_SPEC.input_schema["additionalProperties"] is False
    assert "host_path" not in PREPROCESS_TOOL_SPEC.input_schema["properties"]


def test_prepare_receptor_converts_pdb_to_pdbqt(tmp_path: Path) -> None:
    source = tmp_path / "receptor.pdb"
    source.write_text(PDB_TEXT, encoding="utf-8")

    output = prepare_receptor(source, tmp_path / "receptor.pdbqt")

    assert output.read_text(encoding="utf-8").startswith("ATOM")


def test_prepare_ligand_copies_existing_pdbqt(tmp_path: Path) -> None:
    source = tmp_path / "ligand.pdbqt"
    source.write_text("MODEL 1\nENDMDL\n", encoding="utf-8")

    output = prepare_ligand(source, tmp_path / "prepared.pdbqt")

    assert output.read_text(encoding="utf-8") == "MODEL 1\nENDMDL\n"


def test_convert_format_reports_missing_input(tmp_path: Path) -> None:
    with pytest.raises(PreprocessError, match="does not exist"):
        convert_format(tmp_path / "missing.sdf", tmp_path / "out.pdbqt")


@dataclass
class _Application:
    calls: int = 0

    def request(self, *, invocation):
        self.calls += 1
        assert "host_path" not in invocation.arguments
        return {
            "state": "completed",
            "output_path": "results/ligand.pdbqt",
            "output_digest": DIGEST,
        }


def test_preprocess_runtime_preserves_task_and_never_falls_back() -> None:
    application = _Application()
    runtime = build_preprocess_plugin_runtime_surfaces(application=application).tools[0]
    result = runtime.invoke(
        ToolInvocation(
            call_id="call-1",
            tool_name="enzymedesign.docking.preprocess",
            arguments={
                "operation": "prepare_ligand",
                "input_path": "inputs/ligand.sdf",
                "output_path": "results/ligand.pdbqt",
                "idempotency_key": "prepare-ligand-1",
            },
            session_id="session-1",
            agent_member_id="agent-1",
            task_id="task-1",
        )
    )

    assert result.ok is True
    assert result.payload["fallback_performed"] is False
    assert result.payload["task_finished"] is False
    assert application.calls == 1
