from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from openzyme_runtime import HpcCatalogQuery
from openzyme_runtime import ExecutionPlanDraft
from openzyme_tools import DefaultHpcExecutionRegistry
from openzyme_tools import RepoBackedHpcCatalogProvider


def test_catalog_search_filters_by_capability_and_execution_support() -> None:
    provider = RepoBackedHpcCatalogProvider()

    results = provider.search_catalog(
        HpcCatalogQuery(
            query="pocket",
            stage_tags=("execution",),
            capability_tags=("pocket_detection",),
            execution_support="runnable",
        )
    )

    assert [entry.tool_id for entry in results] == ["fpocket"]


def test_read_skill_extracts_required_sections_and_example() -> None:
    provider = RepoBackedHpcCatalogProvider()

    skill = provider.read_skill("vina")

    assert "receptor_path" in skill.required_inputs
    assert "best affinity estimate" in skill.outputs
    assert skill.example_invocation_shape["ligand_path"] == "ligand.pdbqt"


@dataclass
class FakeHostToolbox:
    resolved: list[dict[str, object]]
    built_requests: list[dict[str, object]]

    def __init__(self) -> None:
        self.resolved = [
            {
                "artifact_id": "art_001",
                "storage_uri": "/tmp/structure.pdb",
                "title": "Focused structure",
            },
            {
                "artifact_id": "art_002",
                "storage_uri": "/tmp/ligand.pdbqt",
                "title": "Prepared ligand",
            }
        ]
        self.built_requests = []

    def resolve_artifacts(self, session_id: str, artifact_ids: list[str]) -> list[dict[str, object]]:
        assert session_id == "sess_001"
        assert artifact_ids == ["art_001"] or artifact_ids == []
        return list(self.resolved) if artifact_ids else []

    def build_execution_request(
        self,
        *,
        execution_subject_id: str,
        execution_subject_label: str,
        execution_mode: str = "auto",
        command: list[str] | None = None,
        resources: dict[str, object] | None = None,
        inputs: list[dict[str, object]] | None = None,
        expected_outputs: list[dict[str, object]] | None = None,
        success_checks: list[dict[str, object]] | None = None,
        failure_signatures: list[dict[str, object]] | None = None,
        metadata: dict[str, object] | None = None,
        tool_name: str = "exec.run",
    ):
        request = {
            "tool_name": tool_name,
            "runspec": {
                "name": f"execution-{execution_subject_id}",
                "stage": "execution",
                "command": command or [],
                "execution_mode": execution_mode,
                "resources": dict(resources or {}),
                "inputs": list(inputs or []),
                "expected_outputs": list(expected_outputs or []),
                "success_checks": list(success_checks or []),
                "failure_signatures": list(failure_signatures or []),
                "metadata": dict(metadata or {}),
            },
        }
        self.built_requests.append(request)

        class _Draft:
            def __init__(self, payload: dict[str, object]) -> None:
                self._payload = payload

            def model_dump(self) -> dict[str, object]:
                return self._payload

        return _Draft(request)


def test_execution_registry_compiles_fpocket_request_from_artifacts() -> None:
    registry = DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider())
    toolbox = FakeHostToolbox()

    payload = registry.compile_request(
        tool_id="fpocket",
        plan=ExecutionPlanDraft(
            catalog_tool_id="fpocket",
            rationale="inspect pockets",
            tool_inputs={},
            execution_mode="ssh",
            expected_result_summary="Pocket ranking",
        ),
        handoff={
            "session_id": "sess_001",
            "execution_goal": "Find pockets",
            "required_artifact_ids": ["art_001"],
            "context_artifact_ids": [],
        },
        host_toolbox=toolbox,
    )

    assert payload["tool_name"] == "exec.run"
    assert "/work/target.pdb" in payload["runspec"]["command"][2]
    assert payload["runspec"]["inputs"] == [
        {
            "artifact_id": "art_001",
            "local_path": "/tmp/structure.pdb",
            "remote_path": "target.pdb",
            "required": True,
            "stage_to": "work",
        }
    ]
    assert payload["runspec"]["expected_outputs"][0]["path"] == "target_out"
    assert payload["runspec"]["metadata"]["catalog_tool_id"] == "fpocket"


def test_execution_registry_compiles_vina_request_from_two_artifacts() -> None:
    registry = DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider())
    toolbox = FakeHostToolbox()

    payload = registry.compile_request(
        tool_id="vina",
        plan=ExecutionPlanDraft(
            catalog_tool_id="vina",
            rationale="dock ligand",
            tool_inputs={"center_x": 1, "center_y": 2, "center_z": 3},
            execution_mode="sbatch",
            expected_result_summary="Docking score",
        ),
        handoff={
            "session_id": "sess_001",
            "execution_goal": "Dock ligand",
            "required_artifact_ids": ["art_001"],
            "context_artifact_ids": [],
        },
        host_toolbox=toolbox,
    )

    assert "--receptor /work/receptor.pdbqt" in payload["runspec"]["command"][2]
    assert "--ligand /work/ligand.pdbqt" in payload["runspec"]["command"][2]
    assert [item["remote_path"] for item in payload["runspec"]["inputs"]] == [
        "receptor.pdbqt",
        "ligand.pdbqt",
    ]
    assert [item["path"] for item in payload["runspec"]["expected_outputs"]] == [
        "vina_out.pdbqt",
        "vina.log",
    ]


def test_execution_registry_rejects_vina_without_ligand() -> None:
    registry = DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider())
    toolbox = FakeHostToolbox()
    toolbox.resolved = toolbox.resolved[:1]

    with pytest.raises(ValueError, match="vina ligand"):
        registry.compile_request(
            tool_id="vina",
            plan=ExecutionPlanDraft(
                catalog_tool_id="vina",
                rationale="dock ligand",
                tool_inputs={},
                execution_mode="sbatch",
                expected_result_summary="Docking score",
            ),
            handoff={
                "session_id": "sess_001",
                "execution_goal": "Dock ligand",
                "required_artifact_ids": ["art_001"],
                "context_artifact_ids": [],
            },
            host_toolbox=toolbox,
        )


def test_execution_registry_rejects_query_only_tools() -> None:
    registry = DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider())

    with pytest.raises(ValueError, match="discovery-only"):
        registry.compile_request(
            tool_id="alphafold3",
            plan=ExecutionPlanDraft(
                catalog_tool_id="alphafold3",
                rationale="predict structure",
                tool_inputs={},
                execution_mode="auto",
                expected_result_summary="Structure prediction",
            ),
            handoff={
                "session_id": "sess_001",
                "execution_goal": "Predict structure",
                "required_artifact_ids": [],
                "context_artifact_ids": [],
            },
            host_toolbox=FakeHostToolbox(),
        )


def test_execution_registry_parses_vina_results_into_structured_findings(tmp_path: Path) -> None:
    registry = DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider())

    @dataclass
    class Outcome:
        raw_result: dict[str, object]

    result_dir = _write_vina_artifacts(tmp_path)
    result = registry.parse_result(
        tool_id="vina",
        outcome=Outcome(raw_result={"best_affinity": -7.2}),
        plan=ExecutionPlanDraft(
            catalog_tool_id="vina",
            rationale="dock ligand",
            tool_inputs={"ligand_path": "/tmp/ligand.pdbqt"},
            execution_mode="ssh",
            expected_result_summary="Affinity estimate",
        ),
        artifact_refs=[
            {
                "artifact_id": "vina_log",
                "storage_uri": str(result_dir / "vina.log"),
            },
            {
                "artifact_id": "vina_pose",
                "storage_uri": str(result_dir / "vina_out.pdbqt"),
            },
        ],
    )

    assert result.structured_findings["design_signal"] == "revise"
    assert result.structured_findings["parser_status"] == "parsed"
    assert result.structured_findings["best_affinity"] == 0.0
    assert result.structured_findings["mode_count"] == 1
    assert result.structured_findings["best_mode"]["rmsd_ub"] == 0.0


def test_execution_registry_parses_fpocket_target_info_from_artifacts(tmp_path: Path) -> None:
    registry = DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider())

    fpocket_out = tmp_path / "target_out" / "target_out"
    fpocket_out.mkdir(parents=True)
    (fpocket_out / "target_info.txt").write_text(
        """Pocket 1 :
\tScore : \t0.928
\tDruggability Score : \t0.907
\tNumber of Alpha Spheres : \t94
\tVolume : \t1006.516

Pocket 2 :
\tScore : \t0.215
\tDruggability Score : \t0.009
\tNumber of Alpha Spheres : \t26
\tVolume : \t326.310
""",
        encoding="utf-8",
    )

    @dataclass
    class Outcome:
        raw_result: dict[str, object]

    result = registry.parse_result(
        tool_id="fpocket",
        outcome=Outcome(raw_result={"pockets_found": 999}),
        plan=ExecutionPlanDraft(
            catalog_tool_id="fpocket",
            rationale="inspect pockets",
            tool_inputs={},
            execution_mode="ssh",
            expected_result_summary="Pocket ranking",
        ),
        artifact_refs=[
            {
                "artifact_id": "fpocket_out",
                "storage_uri": str(tmp_path / "target_out"),
            }
        ],
    )

    assert result.structured_findings["design_signal"] == "proceed"
    assert result.structured_findings["parser_status"] == "parsed"
    assert result.structured_findings["pockets_found"] == 2
    assert result.structured_findings["top_pocket"]["score"] == 0.928
    assert result.structured_findings["top_pocket"]["volume"] == 1006.516


def test_execution_registry_does_not_fabricate_results_when_artifact_missing() -> None:
    registry = DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider())

    @dataclass
    class Outcome:
        raw_result: dict[str, object]

    result = registry.parse_result(
        tool_id="vina",
        outcome=Outcome(raw_result={"best_affinity": -7.2}),
        plan=ExecutionPlanDraft(
            catalog_tool_id="vina",
            rationale="dock ligand",
            tool_inputs={},
            execution_mode="ssh",
            expected_result_summary="Affinity estimate",
        ),
        artifact_refs=[
            {
                "artifact_id": "missing",
                "storage_uri": "/tmp/does-not-exist/vina.log",
            }
        ],
    )

    assert result.structured_findings["design_signal"] == "revise"
    assert result.structured_findings["parser_status"] == "missing_artifact"
    assert "best_affinity" not in result.structured_findings


def _write_vina_artifacts(result_dir: Path) -> Path:
    result_dir.mkdir(exist_ok=True)
    (result_dir / "vina.log").write_text(
        """Detected 96 CPUs
Reading input ... done.
Performing search ... done.

mode |   affinity | dist from best mode
     | (kcal/mol) | rmsd l.b.| rmsd u.b.
-----+------------+----------+----------
   1          0.0      0.000      0.000
Writing output ... done.
""",
        encoding="utf-8",
    )
    (result_dir / "vina_out.pdbqt").write_text("MODEL 1\nENDMDL\n", encoding="utf-8")
    return result_dir
