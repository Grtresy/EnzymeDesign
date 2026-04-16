from __future__ import annotations

from dataclasses import dataclass

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
            }
        ]
        self.built_requests = []

    def resolve_artifacts(self, episode_id: str, artifact_ids: list[str]) -> list[dict[str, object]]:
        assert episode_id == "ep_001"
        assert artifact_ids == ["art_001"] or artifact_ids == []
        return list(self.resolved) if artifact_ids else []

    def build_execution_request(
        self,
        *,
        execution_subject_id: str,
        execution_subject_label: str,
        execution_mode: str = "auto",
        command: list[str] | None = None,
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
            "episode_id": "ep_001",
            "execution_goal": "Find pockets",
            "required_artifact_ids": ["art_001"],
            "context_artifact_ids": [],
        },
        host_toolbox=toolbox,
    )

    assert payload["tool_name"] == "exec.run"
    assert payload["runspec"]["command"] == ["fpocket", "-f", "/tmp/structure.pdb"]
    assert payload["runspec"]["metadata"]["catalog_tool_id"] == "fpocket"


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
                "episode_id": "ep_001",
                "execution_goal": "Predict structure",
                "required_artifact_ids": [],
                "context_artifact_ids": [],
            },
            host_toolbox=FakeHostToolbox(),
        )


def test_execution_registry_parses_vina_results_into_structured_findings() -> None:
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
            tool_inputs={"ligand_path": "/tmp/ligand.pdbqt"},
            execution_mode="ssh",
            expected_result_summary="Affinity estimate",
        ),
        artifact_refs=[{"artifact_id": "art_result"}],
    )

    assert result.structured_findings["design_signal"] == "proceed"
    assert result.structured_findings["best_affinity"] == -7.2
